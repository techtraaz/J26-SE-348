"""Knowledge-graph access. All graph reads go through five fixed functions.

User text never reaches the graph: every parameter is validated first (doc_type
from a fixed list, IDs by a strict regex, year as an integer). There is no
free-text-to-Cypher path anywhere.

Three clients share one interface:
- KGClient()          base; reads mock_data.json (kept as default for back-compat)
- MockKGClient()      explicit name for the JSON-backed client
- LiveKGClient()      talks to a real KG service over HTTP
- FallbackKGClient()  picks per KG_MODE (auto|mock|live)

A fallback to mock happens ONLY on a connection error/timeout, never on a bad
reply, and never in live mode. A mock result must never look live.
"""
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from app import config
from app.schemas.kg import (
    CheckRuleResponse,
    EvidenceChainResponse,
    PeriodTotalsResponse,
    PostingResponse,
    RuleResponse,
)


class KGError(Exception):
    """Base class for all knowledge-graph problems."""


class KGConnectionError(KGError):
    """The KG could not be reached (connection refused, timeout, bad host)."""


class KGProtocolError(KGError):
    """The KG replied, but the reply did not match the expected shape."""


class KGDataError(KGError):
    """The local mock data file is missing or malformed."""


_MOCK_PATH = Path(__file__).with_name("mock_data.json")

# IDs we send to the graph: letters, digits, spaces, dot, underscore, hyphen.
# This allows ordinary text like "match box" but blocks Cypher punctuation.
_ID_RE = re.compile(r"^[A-Za-z0-9 _\-.]{1,64}$")


def _validate_doc_type(doc_type: str) -> str:
    if not isinstance(doc_type, str) or doc_type not in config.ALLOWED_DOC_TYPES:
        raise ValueError(
            f"Rejected doc_type {doc_type!r}: not one of "
            f"{sorted(config.ALLOWED_DOC_TYPES)}.")
    return doc_type


def _validate_id(value: str, kind: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(
            f"Rejected {kind} {value!r}: only letters, digits, spaces, '.', "
            f"'_' and '-' are allowed, max 64 characters.")
    return value


def _validate_year(year: int) -> int:
    if not isinstance(year, int) or isinstance(year, bool) or not 1900 <= year <= 2999:
        raise ValueError(f"Rejected year {year!r}: must be an integer 1900..2999.")
    return year


def _load_mock_file() -> dict:
    """Read the mock file. Missing or malformed data raises, never returns []."""
    if not _MOCK_PATH.exists():
        raise KGDataError(f"mock data file not found: {_MOCK_PATH}")
    try:
        data = json.loads(_MOCK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KGDataError(f"mock data file is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise KGDataError("mock data file must contain a JSON object")
    return data


def _validate_list(model, raw: object, what: str) -> list:
    if not isinstance(raw, list):
        raise KGProtocolError(f"Expected a list for {what}, got {type(raw).__name__}.")
    out = []
    for item in raw:
        try:
            out.append(model.model_validate(item))
        except Exception as exc:  # pydantic ValidationError and friends
            raise KGProtocolError(f"Bad {what} item: {exc}") from exc
    return out


def _validate_one(model, raw: object, what: str):
    try:
        return model.model_validate(raw)
    except Exception as exc:
        raise KGProtocolError(f"Bad {what} reply: {exc}") from exc


class KGClient:
    """Base interface for the five fixed KG functions.

    The base reads mock_data.json, so existing call sites that use KGClient()
    keep working as the mock. Live and fallback clients subclass this and
    override the five doors.
    """

    source: str = "mock"

    def get_rules(self, doc_type: str) -> list[RuleResponse]:
        """POL rules with limits, e.g. dual approval above a threshold."""
        _validate_doc_type(doc_type)
        data = _load_mock_file()
        raw = data.get("rules_by_doc_type", {}).get(doc_type, [])
        return _validate_list(RuleResponse, raw, "rules")

    def get_evidence_chain(self, doc_id: str) -> EvidenceChainResponse:
        """Policy -> control -> transaction -> evidence chain for one doc."""
        _validate_id(doc_id, "doc_id")
        data = _load_mock_file()
        raw = data.get("evidence_chain_by_doc", {}).get(doc_id)
        if raw is None:
            return EvidenceChainResponse(doc_id=doc_id)
        return _validate_one(EvidenceChainResponse, {"doc_id": doc_id, **raw},
                             "evidence chain")

    def get_postings(self, case_id: str) -> list[PostingResponse]:
        """Ledger postings for a case, with account types for side checks."""
        _validate_id(case_id, "case_id")
        data = _load_mock_file()
        raw = data.get("demo_cases", {}).get(case_id, {}).get("postings", [])
        return _validate_list(PostingResponse, raw, "postings")

    def get_period_totals(self, case_id: str, year: int) -> PeriodTotalsResponse:
        """Totals for the equation check, per case and year."""
        _validate_id(case_id, "case_id")
        _validate_year(year)
        data = _load_mock_file()
        by_year = (data.get("demo_cases", {})
                   .get(case_id, {}).get("period_totals", {}))
        raw = by_year.get(str(year))
        if raw is None:
            return PeriodTotalsResponse(year=year)
        return _validate_one(PeriodTotalsResponse, {"year": year, **raw},
                             "period totals")

    def get_check_rules(self, doc_type: str) -> list[CheckRuleResponse]:
        """Data-driven check rules the generic runner evaluates."""
        _validate_doc_type(doc_type)
        data = _load_mock_file()
        raw = data.get("check_rules_by_doc_type", {}).get(doc_type, [])
        return _validate_list(CheckRuleResponse, raw, "check rules")


class MockKGClient(KGClient):
    """Explicit name for the JSON-backed mock client."""

    source = "mock"


class LiveKGClient(KGClient):
    """Talks to a real knowledge-graph service over HTTP.

    Every reply is validated against the Pydantic models. Connection problems
    raise KGConnectionError; an unparsable or wrong-shaped reply raises
    KGProtocolError.
    """

    source = "live"

    def __init__(self, base_url: str | None = None, timeout: float | None = None,
                 fetch: Callable[[str], object] | None = None):
        self.base_url = (config.KG_URL if base_url is None else base_url).rstrip("/")
        self.timeout = config.KG_TIMEOUT if timeout is None else timeout
        self._fetch = fetch or self._http_get

    def _http_get(self, path: str) -> object:
        if not self.base_url:
            raise KGConnectionError("KG_URL is not configured")
        url = self.base_url + path
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise KGConnectionError(f"KG request failed: {exc}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise KGProtocolError(f"KG replied with invalid JSON: {exc}") from exc

    def get_rules(self, doc_type: str) -> list[RuleResponse]:
        _validate_doc_type(doc_type)
        raw = self._fetch(f"/rules/{doc_type}")
        return _validate_list(RuleResponse, raw, "rules")

    def get_evidence_chain(self, doc_id: str) -> EvidenceChainResponse:
        _validate_id(doc_id, "doc_id")
        raw = self._fetch(f"/evidence-chain/{doc_id}")
        return _validate_one(EvidenceChainResponse, raw, "evidence chain")

    def get_postings(self, case_id: str) -> list[PostingResponse]:
        _validate_id(case_id, "case_id")
        raw = self._fetch(f"/postings/{case_id}")
        return _validate_list(PostingResponse, raw, "postings")

    def get_period_totals(self, case_id: str, year: int) -> PeriodTotalsResponse:
        _validate_id(case_id, "case_id")
        _validate_year(year)
        raw = self._fetch(f"/period-totals/{case_id}/{year}")
        return _validate_one(PeriodTotalsResponse, raw, "period totals")

    def get_check_rules(self, doc_type: str) -> list[CheckRuleResponse]:
        _validate_doc_type(doc_type)
        raw = self._fetch(f"/check-rules/{doc_type}")
        return _validate_list(CheckRuleResponse, raw, "check rules")


class FallbackKGClient(KGClient):
    """Chooses live or mock per KG_MODE.

    auto -> try live; on a connection error/timeout only, use mock and mark the
            source "mock_fallback". Bad data is never masked.
    mock -> always mock.
    live -> always live, no fallback.
    """

    def __init__(self, mode: str | None = None, live: KGClient | None = None,
                 mock: KGClient | None = None):
        self.mode = (mode or config.KG_MODE).lower()
        if self.mode not in ("auto", "mock", "live"):
            raise KGError(f"Unknown KG_MODE {self.mode!r}; use auto|mock|live.")
        self._mock = mock or MockKGClient()
        if live is not None:
            self._live = live
        elif config.KG_URL:
            self._live = LiveKGClient()
        else:
            self._live = None
        if self.mode == "live" and self._live is None:
            raise KGError("KG_MODE=live but no KG_URL is configured.")
        if self.mode == "mock":
            self.source = "mock"
        elif self.mode == "live":
            self.source = "live"
        else:
            self.source = "live" if self._live else "mock"

    def _call(self, name: str, *args):
        if self.mode == "mock":
            return getattr(self._mock, name)(*args)
        if self.mode == "live":
            return getattr(self._live, name)(*args)
        if self._live is None:
            self.source = "mock"
            return getattr(self._mock, name)(*args)
        try:
            return getattr(self._live, name)(*args)
        except KGConnectionError:
            self.source = "mock_fallback"
            return getattr(self._mock, name)(*args)

    def get_rules(self, doc_type: str) -> list[RuleResponse]:
        return self._call("get_rules", doc_type)

    def get_evidence_chain(self, doc_id: str) -> EvidenceChainResponse:
        return self._call("get_evidence_chain", doc_id)

    def get_postings(self, case_id: str) -> list[PostingResponse]:
        return self._call("get_postings", case_id)

    def get_period_totals(self, case_id: str, year: int) -> PeriodTotalsResponse:
        return self._call("get_period_totals", case_id, year)

    def get_check_rules(self, doc_type: str) -> list[CheckRuleResponse]:
        return self._call("get_check_rules", doc_type)


def default_kg() -> KGClient:
    """The client the API uses by default, chosen by KG_MODE."""
    return FallbackKGClient()
