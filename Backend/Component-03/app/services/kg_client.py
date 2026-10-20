"""Knowledge-graph access through Component-02's fixed query endpoints.

User text never becomes Cypher: every parameter is validated first (doc_type
from a fixed list, IDs by a strict regex) and only C2's parameterised GET
endpoints are called. C2's POST /query/cypher is never used.

- MockKGClient      reads mock_data.json, or a snapshot of the live KG (KG_MOCK_FILE),
                    in C2's reply shapes
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
from app.schemas.kg import (
    CheckRuleResponse,
    DefinitionInfo,
    LineItemInfo,
    RuleExplanation,
    RuleResponse,
    SectionInfo,
    StandardInfo,
)


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
_SECTION_RE = re.compile(r"^[A-Za-z0-9 _\-.:#]{1,64}$")  # "LKAS 2:9", "CF:4.4"
_TERM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 '\-]{0,79}$")  # a defined term, e.g. "net realisable value"

Transport = Callable[[str, dict], object]
_SEARCH_MODES = ("keyword", "semantic", "hybrid")  # what C2's /query/search accepts


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


def _field_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict) or not all(isinstance(k, str) and isinstance(v, str)
                                            for k, v in raw.items()):
        raise KGProtocolError("Field map must be an object of name -> line-item code.")
    return dict(raw)


def _parsed(what: str, build: Callable[[], object]):
    """Turn C2's nested reply into C3's flat model; a wrong shape is a protocol error."""
    try:
        return build()
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise KGProtocolError(f"Bad {what} reply: {exc}") from exc


def _standard(raw: object) -> StandardInfo | None:
    if raw is None:
        return None
    return _parsed("standard", lambda: StandardInfo(
        **{k: raw["standard"][k] for k in ("code", "title", "status") if raw["standard"].get(k) is not None},
        superseded_by=list(raw.get("superseded_by") or [])))


def _section(raw: object) -> SectionInfo | None:
    if raw is None:
        return None

    def build():
        sec, std = raw["section"], raw.get("standard") or {}
        return SectionInfo(id=sec["id"], number=str(sec.get("number") or ""), heading=sec.get("heading") or "",
                           text=sec.get("text") or "", standard=std.get("code") or "",
                           standard_title=std.get("title") or "", standard_status=std.get("status") or "active",
                           requirements=[r["text"] for r in raw.get("requirements") or [] if r.get("text")])
    return _parsed("section", build)


def _definitions(raw: object) -> list[DefinitionInfo]:
    if raw is None:
        return []
    return _parsed("definitions", lambda: [
        DefinitionInfo(term=d["term"], text=d["text"], defined_in=list(d.get("defined_in") or []))
        for d in raw])


def _line_item(raw: object) -> LineItemInfo | None:
    if raw is None:
        return None

    def build():
        li = raw["line_item"]
        return LineItemInfo(code=li["code"], name=li.get("name") or "", aliases=list(li.get("aliases") or []),
                            statements=[p.get("name") or p.get("statement") for p in raw.get("presented_in") or []],
                            equations=[f"{e['code']}: {e['expression']}" for e in raw.get("equations") or []])
    return _parsed("line item", build)


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

    def get_field_map(self) -> dict[str, str]:
        """Every name a document field may use (line-item code or alias) -> line-item code."""
        return self._cached(("fields",), self._fetch_field_map)

    def get_standard(self, code: str) -> StandardInfo | None:
        """A standard's status, e.g. LKAS 18 superseded by SLFRS 15."""
        validate_id(code, "standard code")
        return self._cached(("standard", code), lambda: self._fetch_standard(code))

    def get_section(self, section_id: str) -> SectionInfo | None:
        """One paragraph of a standard, e.g. 'LKAS 2:9'."""
        if not isinstance(section_id, str) or _SECTION_RE.fullmatch(section_id) is None:
            raise ValueError(f"Rejected section id {section_id!r}")
        return self._cached(("section", section_id), lambda: self._fetch_section(section_id))

    def get_definitions(self, term: str) -> list[DefinitionInfo]:
        term = " ".join(str(term).split()).lower()
        if _TERM_RE.fullmatch(term) is None:
            raise ValueError(f"Rejected term {term!r}")
        return self._cached(("definitions", term), lambda: self._fetch_definitions(term))

    def get_line_item(self, code: str) -> LineItemInfo | None:
        """A line item by its code or any alias, e.g. 'capital'."""
        validate_id(code, "line item")
        return self._cached(("line_item", code), lambda: self._fetch_line_item(code))

    def search(self, text: str, limit: int = 5) -> list[dict]:
        """Search over the standards. Text goes as a query parameter only."""
        text = (text or "").strip()[:200]
        if len(text) < 2:
            return []
        return self._cached(("search", text, limit), lambda: self._fetch_search(text, limit))

    def _fetch_rules(self, doc_type): raise NotImplementedError
    def _fetch_check_rules(self, doc_type): raise NotImplementedError
    def _fetch_chain(self, doc_id): raise NotImplementedError
    def _fetch_explain(self, rule_id): raise NotImplementedError
    def _fetch_search(self, text, limit): raise NotImplementedError
    def _fetch_field_map(self): raise NotImplementedError
    def _fetch_standard(self, code): raise NotImplementedError
    def _fetch_section(self, section_id): raise NotImplementedError
    def _fetch_definitions(self, term): raise NotImplementedError
    def _fetch_line_item(self, code): raise NotImplementedError


class MockKGClient(KGClient):
    """JSON-backed stand-in for C2, using C2's reply shapes."""

    source = "mock"

    def __init__(self, path: Path | None = None) -> None:
        super().__init__()
        self._path = path or _MOCK_PATH
        self._data: dict | None = None

    @property
    def note(self) -> str:
        """Where the mock data comes from, for the audit trace."""
        snap = self._load().get("_snapshot")
        if isinstance(snap, dict):
            return f"KG snapshot taken {snap.get('taken_at', '?')} from {snap.get('kg_url', '?')}"
        return "committed mock data"

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

    def _fetch_field_map(self):
        return _field_map(self._load().get("fields", {}))

    def _fetch_standard(self, code):
        return _standard(self._load().get("standards", {}).get(code))

    def _fetch_section(self, section_id):
        return _section(self._load().get("sections", {}).get(section_id))

    def _fetch_definitions(self, term):
        return _definitions(self._load().get("definitions", {}).get(term))

    def _fetch_line_item(self, code):
        code = self._load().get("fields", {}).get(code, code)
        return _line_item(self._load().get("line_items", {}).get(code))

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

    def _fetch_field_map(self):
        return _field_map(self._get("/query/fields", {}) or {})

    def _fetch_standard(self, code):
        return _standard(self._get(f"/query/standards/{self._seg(code)}", {}))

    def _fetch_section(self, section_id):
        return _section(self._get(f"/query/sections/{self._seg(section_id)}", {}))

    def _fetch_definitions(self, term):
        return _definitions(self._get(f"/query/definitions/{self._seg(term)}", {}))

    def _fetch_line_item(self, code):
        return _line_item(self._get(f"/query/line-items/{self._seg(code)}", {}))

    def _fetch_search(self, text, limit):
        mode = config.KG_SEARCH_MODE if config.KG_SEARCH_MODE in _SEARCH_MODES else "hybrid"
        raw = self._get("/query/search", {"q": text, "mode": mode, "limit": limit})
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
        self._mock = mock or MockKGClient(mock_path())
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

    @property
    def mock_note(self) -> str | None:
        """Where the mock data came from, when the mock answered."""
        if self.source == "live" or not isinstance(self._mock, MockKGClient):
            return None
        return self._mock.note

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

    def get_field_map(self):
        return self._call("get_field_map")

    def get_standard(self, code):
        return self._call("get_standard", code)

    def get_section(self, section_id):
        return self._call("get_section", section_id)

    def get_definitions(self, term):
        return self._call("get_definitions", term)

    def get_line_item(self, code):
        return self._call("get_line_item", code)


def mock_path() -> Path | None:
    """The mock data file: KG_MOCK_FILE when set, else the committed mock."""
    if not config.KG_MOCK_FILE:
        return None
    path = Path(config.KG_MOCK_FILE)
    return path if path.is_absolute() else config.COMPONENT_ROOT / path


def default_kg() -> KGClient:
    """A fresh client per request, chosen by KG_MODE."""
    return FallbackKGClient()
