"""
Evaluation harness: retrieval quality (hit@k) and end-to-end agent behaviour.

    python -m src.evaluate            # FAISS semantic retrieval
    python -m src.evaluate --local    # force the TF-IDF baseline
"""

import argparse
import json
from copy import deepcopy

from .agent import SentinelAgent
from .rag import ROOT, KnowledgeBase
from .simulator import LogisticsSimulator

CASES = ROOT / "data" / "eval_cases.json"


def run(force_local: bool = False, backend: str = "rules", k: int = 4) -> dict:
    kb = KnowledgeBase(force_local=force_local)
    cases = json.loads(CASES.read_text())
    retrieval_hits = action_hits = 0
    rows = []
    for case in cases:
        hits = [h.rule_id for h in kb.retrieve(case["query"], top_k=k)]
        retrieved_ok = any(r in hits for r in case["expected_rules"])

        sim = LogisticsSimulator(seed=0)
        sim.shipments = deepcopy(sim.shipments)
        event = sim.inject_event(case["event_id"])
        result = SentinelAgent(kb=kb, backend=backend).investigate(event, sim.shipments, sim.active_events)
        tools_used = {s["tool"] for s in result["steps"]}
        action_ok = case["expected_action"] in tools_used

        retrieval_hits += retrieved_ok
        action_hits += action_ok
        rows.append({"event": case["event_id"], "retrieved": hits, "retrieval_ok": retrieved_ok, "action_ok": action_ok})
    n = len(cases)
    return {"backend": kb.backend, "cases": n, f"hit@{k}": retrieval_hits / n, "action_accuracy": action_hits / n, "rows": rows}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true")
    ap.add_argument("--backend", default="rules")
    args = ap.parse_args()
    report = run(args.local, args.backend)
    for r in report["rows"]:
        print(f'{r["event"]}  retrieval={"✓" if r["retrieval_ok"] else "✗"}  action={"✓" if r["action_ok"] else "✗"}  {r["retrieved"]}')
    print(f'\nretrieval backend: {report["backend"]} | hit@4: {report["hit@4"]:.0%} | action accuracy: {report["action_accuracy"]:.0%}')
