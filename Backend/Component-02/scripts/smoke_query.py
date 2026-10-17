import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "clients"))

from kg_client_http import HTTPKGClient

# Component 03 mock_data.json values the live graph must return unchanged
C03_CHK_001 = {"rule_id": "CHK-001", "name": "Accounting equation",
               "expression": "assets == liabilities + capital", "severity": "high"}
C03_POL_07 = {"rule_id": "POL-07", "text": "Purchases above Rs. 100,000 need dual approval.",
              "limit": 100000.0}


def in_process_transport():
    from fastapi.testclient import TestClient

    from app.main import app
    client = TestClient(app)

    def get(path, params):
        resp = client.get(path, params={k: v for k, v in params.items() if v is not None})
        return None if resp.status_code == 404 else resp.json()
    return get, client


def checks(kg: HTTPKGClient):
    rules = kg.get_check_rules("balance_sheet")
    chk1 = next((r for r in rules if r["rule_id"] == "CHK-001"), {})
    yield "get_check_rules returns CHK-001 as in C03 mock", \
        {k: chk1.get(k) for k in C03_CHK_001} == C03_CHK_001
    yield "check rule variables map capital -> total_equity", \
        any(v["name"] == "capital" and v["line_item"] == "total_equity"
            for v in chk1.get("variables", []))
    yield "get_rules returns POL-07 as in C03 mock", C03_POL_07 in kg.get_rules("invoice")
    yield "get_evidence_chain starts with the document", kg.get_evidence_chain("BS26")[0] == "BS26"
    yield "get_postings returns a list", isinstance(kg.get_postings("CASE-TV"), list)
    totals = kg.get_period_totals("CASE-TV", 2026)
    yield "get_period_totals has C03 keys", {"assets", "liabilities", "capital", "year"} <= set(totals)
    explained = kg.explain_rule("CHK-011") or {}
    yield "explain CHK-011 cites LKAS 2 para 9", \
        any(c.get("section") == "LKAS 2:9" for c in explained.get("citations", []))
    yield "unknown rule explains to None", kg.explain_rule("NOPE") is None
    section = kg.get_section("LKAS 2:9") or {}
    yield "section LKAS 2:9 has verbatim text", "lower of cost" in (section.get("section") or {}).get("text", "")
    hits = kg.search("LKAS 2:9", mode="keyword")
    yield "search 'LKAS 2:9' goes to the paragraph", bool(hits) and hits[0]["section"] == "LKAS 2:9"
    hits = kg.search("going concern assessment", mode="keyword")
    yield "search 'going concern assessment' finds LKAS 1:25", any(h["section"] == "LKAS 1:25" for h in hits)
    yield "field map knows debit_total", kg.field_map().get("debit_total") == "total_debits"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Check the KG query API end to end")
    ap.add_argument("--base-url", help="running server, e.g. http://localhost:8002 "
                                       "(default: in process against Neo4j from .env)")
    args = ap.parse_args()

    client = None
    if args.base_url:
        kg = HTTPKGClient(args.base_url)
    else:
        transport, client = in_process_transport()
        kg = HTTPKGClient(transport=transport)

    results = list(checks(kg))
    if client is not None:
        write = client.post("/query/cypher", json={"query": "MATCH (n) DETACH DELETE n"})
        read = client.post("/query/cypher", json={"query": "MATCH (s:Standard) RETURN count(s) AS n"})
        results += [("cypher endpoint rejects writes", write.status_code == 400),
                    ("cypher endpoint runs reads", read.status_code == 200
                     and read.json()["rows"][0]["n"] > 0)]
    for name, ok in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}")
    failed = sum(1 for _, ok in results if not ok)
    print(f"\n{len(results) - failed}/{len(results)} passed")
    sys.exit(1 if failed else 0)
