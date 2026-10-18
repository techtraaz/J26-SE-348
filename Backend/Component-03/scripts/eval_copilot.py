"""SO5: Copilot intent accuracy on a labelled query set.

    .venv\\Scripts\\python.exe -m scripts.eval_copilot                 # rules and llm
    .venv\\Scripts\\python.exe -m scripts.eval_copilot --modes rules
    .venv\\Scripts\\python.exe -m scripts.eval_copilot --out eval/results_copilot.json

Reports exact intent accuracy, group accuracy (the proposal's categories), mean
latency and every miss. The LLM is whatever .env configures (C03_LLM_*).
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

from app import config
from app.services import llm
from app.services.copilot import RequestContext, extract, understand
from app.services.copilot.registry import REGISTRY

DEFAULT_SET = Path(__file__).resolve().parents[1] / "eval" / "copilot_intents.jsonl"


def load(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    unknown = {r["intent"] for r in rows} - set(REGISTRY)
    if unknown:
        raise SystemExit(f"labels not in the registry: {sorted(unknown)}")
    return rows


def run(rows: list[dict], mode: str) -> dict:
    config.COPILOT_NLU = mode
    hits = group_hits = 0
    misses, times, methods = [], [], Counter()
    for r in rows:
        ent = extract(r["text"])
        start = time.perf_counter()
        ctx = RequestContext(has_docs=r.get("has_docs", False), case_id=r.get("case_id"),
                             case_audited=r.get("case_audited", False))
        u = understand(r["text"], ent, ctx)
        times.append(time.perf_counter() - start)
        methods[u.method] += 1
        ok = u.intent == r["intent"]
        hits += ok
        group_hits += REGISTRY[u.intent].group == REGISTRY[r["intent"]].group
        if not ok:
            misses.append({"text": r["text"], "expected": r["intent"], "got": u.intent,
                           "method": u.method, "llm_error": u.llm_error})
    n = len(rows)
    return {"mode": mode, "n": n, "accuracy": round(hits / n, 3),
            "group_accuracy": round(group_hits / n, 3),
            "mean_latency_s": round(sum(times) / n, 3),
            "decided_by": dict(methods),
            "model": None if mode == "rules" else f"{config.LLM_PROVIDER}:{config.MODEL_NAME}",
            "misses": misses}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", type=Path, default=DEFAULT_SET)
    ap.add_argument("--modes", default="rules,llm,auto")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rows = load(args.set)
    results = []
    for mode in args.modes.split(","):
        if mode != "rules" and not llm.available():
            print("llm: skipped (LLM not available)")
            continue
        res = run(rows, mode)
        results.append(res)
        print(f"{mode:6} accuracy {res['accuracy']:.1%}  group {res['group_accuracy']:.1%}  "
              f"latency {res['mean_latency_s']:.2f}s  n={res['n']}  {res['decided_by']}  {res['model'] or ''}")
        for m in res["misses"]:
            print(f"   miss: {m['expected']:>16} -> {m['got']:<16} {m['text']}")
    if args.out:
        args.out.write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
