"""Red-team runner. `make redteam`.

Scores on FAILURE MODE, not correctness. The only unacceptable outcomes are a
fabrication (answering a question the schema cannot express, or inventing a
category mapping) and a crash. A false refusal is reported but is safe.
"""
from __future__ import annotations
import collections, pathlib, sys
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.planner import plan_detailed          # noqa: E402
from app.api import answer_spec                # noqa: E402

SUITE = ROOT / "evals" / "redteam.yaml"


def classify(case: dict) -> tuple[str, str, str]:
    """Returns (observed, verdict, detail)."""
    try:
        r = plan_detailed(case["q"])
        out = answer_spec(r.spec, case["q"])
    except Exception as e:                       # noqa: BLE001
        return "CRASH", "FAIL", f"{type(e).__name__}: {str(e)[:80]}"

    if out.clarification:
        observed = "clarified"
    elif out.refused:
        observed = "refused"
    else:
        observed = "answered"

    want = case["outcome"]
    fab = case.get("fabricates_if")
    spec = out.spec or {}
    filters = {k: v for k, v in (spec.get("filters") or {}).items() if v}

    # An invented mapping is a fabrication even if the sentence looks plausible.
    if fab and observed == "answered" and filters.get(fab):
        return observed, "FAIL", f"FABRICATED {fab}={filters[fab]!r}"

    if want == "must_refuse":
        return observed, ("PASS" if observed in ("refused", "clarified") else "FAIL"), \
            "fabricated an answer" if observed == "answered" else out.answer[:70]
    if want == "must_answer":
        return observed, ("PASS" if observed == "answered" else "WARN"), \
            "false refusal: " + out.answer[:60] if observed != "answered" else out.answer[:70]
    if want == "clarify_ok":
        return observed, ("PASS" if observed in ("clarified", "refused") else "FAIL"), out.answer[:70]
    return observed, "PASS", out.answer[:70]      # either


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="planner model override, e.g. qwen3:1.7b")
    a = ap.parse_args()
    if a.model:
        from app.llm import set_model
        set_model("planner", a.model)
    from app.llm import MODELS
    print(f"planner: {MODELS['planner']}   escalate: {MODELS['escalate']}\n")

    cases = yaml.safe_load(SUITE.read_text())
    by_cat = collections.defaultdict(list)
    fails, warns = [], []
    print(f"{'id':16} {'cat':10} {'observed':10} {'verdict':7} detail")
    print("-" * 100)
    for c in cases:
        observed, verdict, detail = classify(c)
        by_cat[c["cat"]].append(verdict)
        (fails if verdict == "FAIL" else warns if verdict == "WARN" else []).append((c["id"], detail))
        flag = "  " if verdict == "PASS" else "!!" if verdict == "FAIL" else " ~"
        print(f"{flag}{c['id']:14} {c['cat']:10} {observed:10} {verdict:7} {detail[:60]}")

    print("\n### Red-team summary")
    print(f"| category | pass | warn | FAIL |\n|---|---:|---:|---:|")
    for cat, vs in by_cat.items():
        print(f"| {cat} | {vs.count('PASS')} | {vs.count('WARN')} | {vs.count('FAIL')} |")
    print(f"\nfabrications / crashes: {len(fails)}    false refusals: {len(warns)}    "
          f"total: {len(cases)}")
    # With a small planner and a larger escalation tier, an escalated answer is
    # not the small model's answer. Make that visible or the comparison lies.
    try:
        from app.llm import efficiency_report
        r = efficiency_report()
        print(f"model calls: {r['calls']}   escalations: {r['escalations']} "
              f"({r['escalation_rate']:.0%})   by model: {r['by_model']}")
    except Exception:
        pass
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
