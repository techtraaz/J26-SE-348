"""Field mapping quality on labelled Component-01 documents (eval/field_mapping/*.json).

    .venv\\Scripts\\python.exe -m scripts.eval_fields                  # rules, then rules + LLM
    .venv\\Scripts\\python.exe -m scripts.eval_fields --modes rules
    .venv\\Scripts\\python.exe -m scripts.eval_fields --out eval/results_fields.json

A field counts as correct when its name and value (within 1 cent) match the
label. Precision = correct / fields read; recall = correct / fields labelled.
Each sample: {"input": {"extraction" | "verified": ...}, "expected": {"doc_type",
"period_year", "fields": {...}}}. The KG is whatever .env configures (mock by default).
"""
import argparse
import json
import time
from pathlib import Path

from app import config
from app.services import llm
from app.services.c1_review import C1Input, preview
from app.services.kg_client import default_kg

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "eval" / "field_mapping"


def _same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, (int, float)):
        return abs(a - b) <= config.AMOUNT_TOLERANCE
    return a == b


def run(samples: list[dict], use_llm: bool) -> dict:
    config.LLM_ENABLED = use_llm
    kg = default_kg()
    read = correct = labelled = type_ok = year_ok = 0
    errors, times = [], []
    for s in samples:
        start = time.perf_counter()
        p = preview("EVAL", [C1Input.model_validate(s["input"])], kg)[0]
        times.append(time.perf_counter() - start)
        got = {f["field"]: f["value"] for f in p["fields"]}
        want = s["expected"]["fields"]
        hits = {k for k, v in want.items() if k in got and _same(got[k], v)}
        read, correct, labelled = read + len(got), correct + len(hits), labelled + len(want)
        type_ok += p["doc_type"] == s["expected"]["doc_type"]
        year = (p["suggestions"]["period_year"] or {}).get("value")
        year_ok += year == s["expected"]["period_year"]
        for k in set(want) | set(got):
            if k not in hits:
                errors.append({"sample": s["name"], "field": k, "expected": want.get(k), "got": got.get(k)})
    n = len(samples)
    return {"mode": "rules+llm" if use_llm else "rules", "documents": n,
            "precision": round(correct / read, 3) if read else 0.0,
            "recall": round(correct / labelled, 3) if labelled else 0.0,
            "doc_type_accuracy": round(type_ok / n, 3), "year_accuracy": round(year_ok / n, 3),
            "mean_latency_s": round(sum(times) / n, 3), "errors": errors}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--modes", default="rules,llm")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    samples = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.dir.glob("*.json"))]
    llm_ready = config.LLM_ENABLED and llm.available()  # checked before any mode switches it off
    results = []
    for mode in args.modes.split(","):
        if mode == "llm" and not llm_ready:
            print("rules+llm: skipped (LLM not available)")
            continue
        res = run(samples, use_llm=mode == "llm")
        results.append(res)
        print(f"{res['mode']:10} precision {res['precision']:.1%}  recall {res['recall']:.1%}  "
              f"type {res['doc_type_accuracy']:.0%}  year {res['year_accuracy']:.0%}  "
              f"latency {res['mean_latency_s']:.2f}s  n={res['documents']}")
        for e in res["errors"]:
            print(f"   {e['sample']}: {e['field']} expected {e['expected']!r} got {e['got']!r}")
    if args.out:
        args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
