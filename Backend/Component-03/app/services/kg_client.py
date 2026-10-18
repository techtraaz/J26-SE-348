"""Knowledge-graph access through Component-02's fixed query endpoints.

User text never becomes Cypher: every parameter is validated first (doc_type
from a fixed list, IDs by a strict regex) and only C2's parameterised GET
endpoints are called. C2's POST /query/cypher is never used.

- MockKGClient      reads mock_data.json (same shapes as C2)
- LiveKGClient      calls C2 over HTTP (standard library only)
- FallbackKGClient  picks per KG_MODE; in auto mode switches to mock only when
                    C2 is unreachable, and says so (source "mock_fallback")

Each client caches replies for its own lifetime. default_kg() makes one per
request, so a run sees one consistent KG snapshot and repeats no calls.
"""
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from app import config
from app.schemas.kg import CheckRuleResponse, RuleExplanation, RuleResponse


class KGError(Exception):
    """Base class for all knowledge-graph problems."""


class KGUnavailable(KGError):
    """C2 could not be reached, or reported its graph database down (503)."""


class KGProtocolError(KGError):
    """C2 replied, but not with the agreed shape or status."""


class KGDataError(KGError):
    """The local mock data file is missing or malformed."""


_MOCK_PATH = Path(__file__).with_name("mock_data.json")
_ID_RE = re.compile(r"^[A-Za-z0-9 _\-.]{1,64}$")

Transport = Callable[[str, dict], object]


def validate_doc_type(doc_type: str) -> str:
    if not isinstance(doc_type, str) or doc_type not in config.ALLOWED_DOC_TYPES:
        raise ValueError(f"Rejected doc_type {doc_type!r}: not a supported document type.")
    return doc_type


def validate_id(value: str, kind: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"Rejected {kind} {value!r}: only letters, digits, spaces, "
                         f"'.', '_' and '-' are allowed, max 64 characters.")
    return value


def _models(model, raw: object, what: str) -> list:
    if not isinstance(raw, list):
        raise KGProtocolError(f"Expected a list for {what}, got {type(raw).__name__}.")
    try:
        return [model.model_validate(item) for item in raw]
    except Exception as exc:  # pydantic ValidationError
        raise KGProtocolError(f"Bad {what} item: {exc}") from exc


def _chain(raw: object, doc_id: str) -> list[str]:
    """C2 returns [doc_id, ...linked doc ids]."""
    if raw is None:
        return [doc_id]
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise KGProtocolError("Evidence chain must be a list of document IDs.")
    return list(raw) or [doc_id]


def _explanation(raw: object) -> RuleExplanation | None:
    if raw is None:
        return None
    try:
        return RuleExplanation.model_validate(raw)
    except Exception as exc:
        raise KGProtocolError(f"Bad rule explanation: {exc}") from exc


class KGClient:
    """Interface of the KG doors C3 uses. Subclasses implement _fetch_*."""

    source: str = "mock"

    def __init__(self) -> None:
        self._cache: dict[tuple, object] = {}
        self._lock = threading.Lock()

    def _cached(self, key: tuple, load: Callable[[], object]):
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        value = load()
        with self._lock:
            self._cache[key] = value
        return value

    def get_rules(self, doc_type: str) -> list[RuleResponse]:
        """Policy rules with limits, e.g. POL-07 dual approval."""
        validate_doc_type(doc_type)
        return self._cached(("rules", doc_type), lambda: self._fetch_rules(doc_type))

    def get_check_rules(self, doc_type: str) -> list[CheckRuleResponse]:
        """Machine-checkable rules for a document type."""
        validate_doc_type(doc_type)
        return self._cached(("check", doc_type), lambda: self._fetch_check_rules(doc_type))

    def get_evidence_chain(self, doc_id: str) -> list[str]:
        """The document plus every document linked to it in the KG."""
        validate_id(doc_id, "doc_id")
        return self._cached(("chain", doc_id), lambda: self._fetch_chain(doc_id))

    def explain_rule(self, rule_id: str) -> RuleExplanation | None:
        """Where a rule comes from (standards, paragraphs) and one sentence."""
        validate_id(rule_id, "rule_id")
        return self._cached(("explain", rule_id), lambda: self._fetch_explain(rule_id))

    def search(self, text: str, limit: int = 5) -> list[dict]:
        """Keyword search over the standards. Text goes as a query parameter only."""
        text = (text or "").strip()[:200]
        if len(text) < 2:
            return []
        return self._cached(("search", text, limit), lambda: self._fetch_search(text, limit))

    def _fetch_rules(self, doc_type): raise NotImplementedError
    def _fetch_check_rules(self, doc_type): raise NotImplementedError
    def _fetch_chain(self, doc_id): raise NotImplementedError
    def _fetch_explain(self, rule_id): raise NotImplementedError
    def _fetch_search(self, text, limit): raise NotImplementedError


class MockKGClient(KGClient):
    """JSON-backed stand-in for C2, using C2's reply shapes."""

    source = "mock"

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self._path = path or _MOCK_PATH
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is None:
            if not self._path.exists():
                raise KGDataError(f"mock data file not found: {self._path}")
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise KGDataError(f"mock data file is not valid JSON: {exc}") from exc
            if not isinstance(data, dict):
                raise KGDataError("mock data file must contain a JSON object")
            self._data = data
        return self._data

    def _fetch_rules(self, doc_type):
        return _models(RuleResponse, self._load().get("rules", {}).get(doc_type, []), "rules")

    def _fetch_check_rules(self, doc_type):
        return _models(CheckRuleResponse,
                       self._load().get("check_rules", {}).get(doc_type, []), "check rules")

    def _fetch_chain(self, doc_id):
        return _chain(self._load().get("evidence_chains", {}).get(doc_id), doc_id)

    def _fetch_explain(self, rule_id):
        return _explanation(self._load().get("explanations", {}).get(rule_id))

    def _fetch_search(self, text, limit):
        words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2]
        hits = [r for r in self._load().get("search", [])
                if any(w in str(r.get("text", "")).lower() for w in words)]
        return hits[:limit]


class LiveKGClient(KGClient):
    """Calls C2's /query endpoints. 404 means "not found" (an empty answer)."""

    source = "live"

    def __init__(self, base_url: str | None = None, timeout: float | None = None,
                 transport: Transport | None = None) -> None:
        super().__init__()
        self.base_url = (config.KG_URL if base_url is None else base_url).rstrip("/")
        self.timeout = config.KG_TIMEOUT if timeout is None else timeout
        self._get = transport or self._http_get

    def _http_get(self, path: str, params: dict) -> object:
        if not self.base_url:
            raise KGUnavailable("KG_URL is not configured")
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = self.base_url + path + (f"?{query}" if query else "")
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:  # must come before URLError (subclass)
            if exc.code == 404:
                return None
            if exc.code == 503:
                raise KGUnavailable(f"KG reports its graph database down ({path})") from exc
            raise KGProtocolError(f"KG returned HTTP {exc.code} for {path}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise KGUnavailable(f"KG not reachable at {self.base_url}: {exc}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise KGProtocolError(f"KG replied with invalid JSON for {path}") from exc

    @staticmethod
    def _seg(value: str) -> str:
        return urllib.parse.quote(value, safe="")

    def _fetch_rules(self, doc_type):
        raw = self._get(f"/query/rules/{self._seg(doc_type)}", {})
        return _models(RuleResponse, raw or [], "rules")

    def _fetch_check_rules(self, doc_type):
        raw = self._get(f"/query/check-rules/{self._seg(doc_type)}", {})
        return _models(CheckRuleResponse, raw or [], "check rules")

    def _fetch_chain(self, doc_id):
        return _chain(self._get(f"/query/evidence-chain/{self._seg(doc_id)}", {}), doc_id)

    def _fetch_explain(self, rule_id):
        return _explanation(self._get(f"/query/rules/{self._seg(rule_id)}/explain", {}))

    def _fetch_search(self, text, limit):
        raw = self._get("/query/search", {"q": text, "mode": "keyword", "limit": limit})
        if raw is None:
            return []
        if not isinstance(raw, dict) or not isinstance(raw.get("results", []), list):
            raise KGProtocolError("Search reply must be an object with a results list.")
        return raw.get("results", [])


class FallbackKGClient(KGClient):
    """auto -> live; on KGUnavailable switch to mock for the rest of this client's
               life (no repeated timeouts) and report source "mock_fallback".
               A bad reply is never masked.
    mock -> always mock.   live -> always live, errors surface."""

    def __init__(self, mode: str | None = None, live: KGClient | None = None,
                 mock: KGClient | None = None) -> None:
        super().__init__()
        self.mode = (mode or config.KG_MODE).lower()
        if self.mode not in ("auto", "mock", "live"):
            raise KGError(f"Unknown KG_MODE {self.mode!r}; use auto|mock|live.")
        self._mock = mock or MockKGClient()
        self._live = live if live is not None else (LiveKGClient() if config.KG_URL else None)
        if self.mode == "live" and self._live is None:
            raise KGError("KG_MODE=live but no KG_URL is configured.")
        self.fallback_reason: str | None = None
        if self.mode == "mock" or self._live is None:
            self.source = "mock"
        else:
            self.source = "live"

    def _call(self, name: str, *args):
        if self.source == "mock" or (self.mode == "auto" and self.fallback_reason):
            return getattr(self._mock, name)(*args)
        if self.mode == "live":
            return getattr(self._live, name)(*args)
        try:
            return getattr(self._live, name)(*args)
        except KGUnavailable as exc:
            self.fallback_reason = str(exc)
            self.source = "mock_fallback"
            return getattr(self._mock, name)(*args)

    def get_rules(self, doc_type):
        return self._call("get_rules", doc_type)

    def get_check_rules(self, doc_type):
        return self._call("get_check_rules", doc_type)

    def get_evidence_chain(self, doc_id):
        return self._call("get_evidence_chain", doc_id)

    def explain_rule(self, rule_id):
        return self._call("explain_rule", rule_id)

    def search(self, text, limit=5):
        return self._call("search", text, limit)


def default_kg() -> KGClient:
    """A fresh client per request, chosen by KG_MODE."""
    return FallbackKGClient()
