"""Save a snapshot of the live KG so C3 can be run and tuned without C2.

    .venv\\Scripts\\python.exe -m scripts.snapshot_kg                  # KG_URL from .env
    .venv\\Scripts\\python.exe -m scripts.snapshot_kg --url http://localhost:8002
    .venv\\Scripts\\python.exe -m scripts.snapshot_kg --compare        # snapshot vs committed mock

The snapshot holds C2's raw replies in the mock's layout: every rule per
document type, rule explanations, the field map, line items, and the standards,
sections and definitions reachable from them, plus search results for a fixed
set of questions. C2 has no "list everything" endpoint, so sections and
standards are found by following the references in each reply.

It is written to data/kg_snapshot.json (gitignored). Use it with
KG_MOCK_FILE=data/kg_snapshot.json in .env; tests keep using the committed mock.
Exit code: 0 saved, 1 saved with problems, 2 C2 not reachable.
"""
import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from app import config
from app.services.kg_client import (
    KGProtocolError,
    KGUnavailable,
    LiveKGClient,
    MockKGClient,
)
from scripts.check_kg_contract import run_checks

DEFAULT_OUT = config.COMPONENT_ROOT / "data" / "kg_snapshot.json"
COMMITTED_MOCK = config.COMPONENT_ROOT / "app" / "services" / "mock_data.json"
SNAPSHOT_FORMAT = 1
MAX_SECTIONS = 400  # bounds the crawl; each section is one request
SEARCH_LIMIT = 10
# Questions an auditor asks the Copilot; rule names and line items are added.
SEARCH_QUESTIONS = (
    "how should inventories be measured", "net realisable value", "revenue recognition",
    "going concern", "fraud risk", "management override of controls", "materiality",
    "audit evidence", "analytical procedures", "subsequent events", "cash and cash equivalents",
    "statement of cash flows", "property plant and equipment depreciation", "impairment of assets",
    "leases", "provisions and contingent liabilities", "related party disclosures",
    "accounting equation assets liabilities equity", "current and non-current classification",
    "dual approval of purchases", "cut-off of transactions", "external confirmations",
)
_SECTION_REF = re.compile(r"^[A-Za-z]{2,6}(?: \d{1,4})?:\d[0-9A-Za-z.]*$")  # "LKAS 2:9", "CF:4.4"
_STANDARD_REF = re.compile(r"^(?:LKAS|SLFRS|SLAuS|SLAS|SLFRS for SMEs) \d{1,4}$|^CF$")


def _refs(raw: object) -> tuple[set[str], set[str], set[str]]:
    """(section ids, standard codes, defined terms) mentioned anywhere in a reply."""
    sections, standards, terms = set(), set(), set()

    def walk(v: object) -> None:
        if isinstance(v, dict):
            if isinstance(v.get("term"), str):
                terms.add(" ".join(v["term"].split()).lower())
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            if _SECTION_REF.fullmatch(v):
                sections.add(v)
                standards.add(v.split(":", 1)[0])
            elif _STANDARD_REF.fullmatch(v):
                standards.add(v)
    walk(raw)
    return sections, standards, terms


class Snapshot:
    def __init__(self, kg: LiveKGClient) -> None:
        self.kg = kg
        self.problems: list[str] = []
        self.data: dict = {"rules": {}, "check_rules": {}, "evidence_chains": {}, "explanations": {},
                           "search": [], "fields": {}, "standards": {}, "sections": {},
                           "definitions": {}, "line_items": {}}
        self._seen: dict[str, set[str]] = {"sections": set(), "standards": set(), "definitions": set()}
        self._todo: dict[str, set[str]] = {"sections": set(), "standards": set(), "definitions": set()}

    def get(self, path: str, params: dict | None = None) -> object:
        """C2's raw reply; a bad reply is noted and skipped, C2 down stops the snapshot."""
        try:
            return self.kg._get(path, params or {})
        except KGProtocolError as exc:
            self.problems.append(f"{path}: {exc}")
            return None

    def follow(self, raw: object) -> None:
        sections, standards, terms = _refs(raw)
        for kind, found in (("sections", sections), ("standards", standards), ("definitions", terms)):
            self._todo[kind] |= found - self._seen[kind]

    def take(self) -> dict:
        seg = self.kg._seg
        d = self.data
        d["fields"] = self.get("/query/fields") or {}
        for doc_type in sorted(config.ALLOWED_DOC_TYPES - {"unknown"}):
            for key, path in (("rules", "rules"), ("check_rules", "check-rules")):
                raw = self.get(f"/query/{path}/{seg(doc_type)}")
                if raw:
                    d[key][doc_type] = raw
        rule_ids = sorted({r["rule_id"] for key in ("rules", "check_rules") for rs in d[key].values()
                           for r in rs if isinstance(r, dict) and "rule_id" in r})
        for rule_id in rule_ids:
            raw = self.get(f"/query/rules/{seg(rule_id)}/explain")
            if raw is not None:
                d["explanations"][rule_id] = raw
                self.follow(raw)
        for code in sorted(set(d["fields"].values())):
            raw = self.get(f"/query/line-items/{seg(code)}")
            if raw is not None:
                d["line_items"][code] = raw
                self.follow(raw)
        self._crawl()
        self._search(rule_ids)
        return d

    def _crawl(self) -> None:
        seg, d = self.kg._seg, self.data
        paths = {"sections": "sections", "standards": "standards", "definitions": "definitions"}
        while any(self._todo.values()):
            for kind in ("standards", "sections", "definitions"):
                while self._todo[kind]:
                    key = self._todo[kind].pop()
                    self._seen[kind].add(key)
                    if kind == "sections" and len(d["sections"]) >= MAX_SECTIONS:
                        self.problems.append(f"stopped at {MAX_SECTIONS} sections; raise MAX_SECTIONS")
                        self._todo["sections"].clear()
                        break
                    raw = self.get(f"/query/{paths[kind]}/{seg(key)}")
                    if raw:
                        d[kind][key] = raw
                        self.follow(raw)

    def _search(self, rule_ids: list[str]) -> None:
        d = self.data
        names = [r.get("name", "") for rs in d["check_rules"].values() for r in rs if isinstance(r, dict)]
        items = [v.get("line_item", {}).get("name", "") for v in d["line_items"].values() if isinstance(v, dict)]
        questions = list(dict.fromkeys(q.lower() for q in [*SEARCH_QUESTIONS, *names, *items] if len(q) > 2))
        mode = config.KG_SEARCH_MODE if config.KG_SEARCH_MODE in ("keyword", "semantic", "hybrid") else "hybrid"
        seen: set[tuple] = set()
        notes = set()
        for q in questions:
            raw = self.get("/query/search", {"q": q, "mode": mode, "limit": SEARCH_LIMIT})
            if not isinstance(raw, dict):
                continue
            if raw.get("note"):
                notes.add(raw["note"])
            for hit in raw.get("results", []) or []:
                key = (hit.get("section"), str(hit.get("text", ""))[:200])
                if key not in seen:
                    seen.add(key)
                    d["search"].append(hit)
        self.search_info = {"mode": mode, "questions": len(questions), "notes": sorted(notes)}


def take_snapshot(url: str, out: Path, kg: LiveKGClient | None = None) -> tuple[Path, list[str], list[str]]:
    """Save the snapshot; returns (path, problems while taking it, contract problems)."""
    kg = kg or LiveKGClient(url)
    health = kg._get("/health", {})  # raises KGUnavailable when C2 is down
    snap = Snapshot(kg)
    data = snap.take()
    counts = {k: len(v) for k, v in data.items()}
    data = {
        "_about": "Snapshot of the live Component-02 KG for offline C3 runs. Local only, not committed.",
        "_snapshot": {"format": SNAPSHOT_FORMAT, "taken_at": datetime.now(UTC).isoformat(timespec="seconds"),
                      "kg_url": url, "health": health, "counts": counts, "search": snap.search_info,
                      "problems": snap.problems},
        **data}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)
    # The snapshot must work as mock data: run the same contract checks on it.
    report = run_checks(MockKGClient(out), health if isinstance(health, dict) else None)
    return out, snap.problems, report.problems


# --- comparing a snapshot with the committed mock -------------------------------

def _rules_by_id(data: dict) -> dict[str, dict]:
    out = {}
    for key in ("rules", "check_rules"):
        for doc_type, rs in data.get(key, {}).items():
            for r in rs:
                entry = out.setdefault(r["rule_id"], {**r, "doc_types": set()})
                entry["doc_types"].add(doc_type)
    return out


def _explained(e: dict | None) -> dict:
    e = e or {}
    cites = sorted(c.get("section") or c.get("standard") or "" for c in e.get("citations", []))
    return {"citations": cites, "assertions": sorted(e.get("assertions", [])), "risks": sorted(e.get("risks", []))}


def compare(mock: dict, snap: dict) -> list[str]:
    """What the committed mock has different from the live KG snapshot."""
    lines = []
    a, b = _rules_by_id(mock), _rules_by_id(snap)
    for rid in sorted(set(a) | set(b)):
        if rid not in b:
            lines.append(f"{rid}: in the mock only")
            continue
        if rid not in a:
            lines.append(f"{rid}: in the live KG only ({b[rid].get('name') or b[rid].get('text')})")
            continue
        for k in ("name", "text", "expression", "severity", "limit", "required_approvals", "doc_types"):
            if a[rid].get(k) != b[rid].get(k):
                lines.append(f"{rid} {k}: mock {a[rid].get(k)!r}, live {b[rid].get(k)!r}")
        va = {v["name"]: v for v in a[rid].get("variables", [])}
        vb = {v["name"]: v for v in b[rid].get("variables", [])}
        if va != vb:
            lines.append(f"{rid} variables: mock {sorted(va)}, live {sorted(vb)} (or their line items/aliases differ)")
        ea, eb = _explained(mock["explanations"].get(rid)), _explained(snap["explanations"].get(rid))
        for k in ea:
            if ea[k] != eb[k]:
                lines.append(f"{rid} {k}: mock {ea[k]}, live {eb[k]}")
    fa, fb = mock.get("fields", {}), snap.get("fields", {})
    for name in sorted(set(fa) | set(fb)):
        if fa.get(name) != fb.get(name):
            lines.append(f"field {name!r}: mock {fa.get(name)!r}, live {fb.get(name)!r}")
    for code in sorted(set(mock.get("standards", {})) & set(snap.get("standards", {}))):
        sa = (mock["standards"][code].get("standard") or {}).get("status")
        sb = (snap["standards"][code].get("standard") or {}).get("status")
        if sa != sb:
            lines.append(f"standard {code} status: mock {sa!r}, live {sb!r}")
    for k in ("standards", "sections", "definitions", "line_items", "search"):
        lines.append(f"{k}: mock {len(mock.get(k, {}))}, live {len(snap.get(k, {}))}")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=config.KG_URL, help="C2 base URL (default: KG_URL)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to save the snapshot")
    ap.add_argument("--compare", action="store_true", help="compare an existing snapshot with the committed mock")
    args = ap.parse_args()
    if args.compare:
        if not args.out.exists():
            print(f"No snapshot at {args.out}; take one first.")
            return 2
        snap = json.loads(args.out.read_text(encoding="utf-8"))
        mock = json.loads(COMMITTED_MOCK.read_text(encoding="utf-8"))
        print(f"Committed mock vs snapshot taken {snap.get('_snapshot', {}).get('taken_at', '?')}:")
        print("\n".join(f"  {line}" for line in compare(mock, snap)))
        return 0
    if not args.url:
        print("No C2 address: set KG_URL in .env or pass --url http://localhost:8002")
        return 2
    try:
        out, problems, contract = take_snapshot(args.url, args.out)
    except KGUnavailable as exc:
        print(f"C2 is not reachable at {args.url}: {exc}\n"
              "Start C2 (port 8002) and make sure its Neo4j database is running.")
        return 2
    counts = json.loads(out.read_text(encoding="utf-8"))["_snapshot"]["counts"]
    print(f"Saved {out}\n  " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for p in problems:
        print(f"  problem while taking it: {p}")
    for p in contract:
        print(f"  contract problem in the snapshot: {p}")
    shown = out.resolve()
    if shown.is_relative_to(config.COMPONENT_ROOT):
        shown = shown.relative_to(config.COMPONENT_ROOT)
    print(f"Use it: set KG_MOCK_FILE={shown.as_posix()} in .env (KG_MODE=mock to never touch C2).")
    return 1 if problems or contract else 0


if __name__ == "__main__":
    sys.exit(main())
