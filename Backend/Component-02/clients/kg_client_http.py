"""HTTP client for the Component 02 knowledge graph.

Same method names and return shapes as Component 03's KGClient (app/services/kg_client.py),
so it can replace the mock without changing the agents. Standard library only.

    from kg_client_http import HTTPKGClient
    kg = HTTPKGClient("http://localhost:8002")
    kg.get_check_rules("balance_sheet")
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable


class KGUnavailable(RuntimeError):
    pass


def _urllib_transport(base_url: str, timeout: float) -> Callable[[str, dict], object]:
    def get(path: str, params: dict) -> object:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url = f"{base_url.rstrip('/')}{path}" + (f"?{query}" if query else "")
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise KGUnavailable(f"KG returned {exc.code} for {path}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise KGUnavailable(f"KG not reachable at {base_url}: {exc}") from exc
    return get


def _seg(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


class HTTPKGClient:
    def __init__(self, base_url: str = "http://localhost:8002", timeout: float = 10.0,
                 transport: Callable[[str, dict], object] | None = None):
        self._get = transport or _urllib_transport(base_url, timeout)

    # same methods as Component 03 KGClient

    def get_rules(self, doc_type: str) -> list[dict]:
        return self._get(f"/query/rules/{_seg(doc_type)}", {}) or []

    def get_check_rules(self, doc_type: str) -> list[dict]:
        return self._get(f"/query/check-rules/{_seg(doc_type)}", {}) or []

    def get_evidence_chain(self, doc_id: str) -> list[str]:
        return self._get(f"/query/evidence-chain/{_seg(doc_id)}", {}) or [doc_id]

    def get_postings(self, case_id: str) -> list[dict]:
        return self._get(f"/query/postings/{_seg(case_id)}", {}) or []

    def get_period_totals(self, case_id: str, year: int) -> dict:
        return self._get(f"/query/period-totals/{_seg(case_id)}", {"year": year}) or {
            "assets": 0.0, "liabilities": 0.0, "capital": 0.0, "year": year}

    # extras for explanations and citations

    def explain_rule(self, rule_id: str) -> dict | None:
        return self._get(f"/query/rules/{_seg(rule_id)}/explain", {})

    def get_section(self, section_id: str) -> dict | None:
        return self._get(f"/query/sections/{_seg(section_id)}", {})

    def search(self, q: str, mode: str = "hybrid", limit: int = 5,
               standard: str | None = None) -> list[dict]:
        out = self._get("/query/search", {"q": q, "mode": mode, "limit": limit,
                                          "standard": standard})
        return out["results"] if out else []

    def field_map(self) -> dict[str, str]:
        return self._get("/query/fields", {}) or {}
