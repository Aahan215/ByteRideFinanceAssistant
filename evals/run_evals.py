"""Accuracy harness. `make eval`.

Scores three things separately, because they fail for different reasons:

  spec  -- did the planner understand the question?
  value -- did the pipeline compute the same number the verified spec gives?
  refusal -- did it decline when the data cannot answer?

Expected VALUES are never hand-written. They are derived by running the
hand-verified `expect_spec` through the same engine, so a human only ever
checks an interpretation, never arithmetic.

    python evals/run_evals.py                      # current configured model
    python evals/run_evals.py --model qwen2.5:3b   # candidate comparison
    python evals/run_evals.py --stub               # no model at all
    python evals/run_evals.py --out report.md      # markdown for the deck
"""
from __future__ import annotations
import argparse, collections, pathlib, sys, time

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.spec import QuerySpec                                    # noqa: E402
from app.api import answer_spec                                   # noqa: E402

GOLDEN = ROOT / "evals" / "golden.yaml"


def subset_match(got: dict, want) -> bool:
    """`expect_spec` lists only the fields that matter, so this is a subset
    comparison -- a case does not have to restate every default."""
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return False
        return all(subset_match(got.get(k), v) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(got, list) and len(got) == len(want) and \
            all(subset_match(g, w) for g, w in zip(got, want))
    # A vendor that resolved to a family of branch-suffixed names satisfies an
    # expectation naming the canonical one: "DMart" -> every DMART AVENUE
    # SUPERMARTS branch is the answer the user wanted, not a mismatch.
    if isinstance(got, list) and isinstance(want, str):
        return want in got
    return got == want


def metric_value(ans) -> float | None:
    if not ans.breakdown:
        return None
    row = ans.breakdown[0]
    return row.get(ans.spec["metric"]) if ans.spec else list(row.values())[-1]


def run_case(case, planner, priors: dict):
    prior = priors.get(case.get("after"))
    t0 = time.perf_counter()
    result = planner(case["question"], prior)
    latency = time.perf_counter() - t0
    spec = result if isinstance(result, QuerySpec) else result.spec
    priors[case["id"]] = spec
    return spec, latency


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="override the planner model (e.g. qwen2.5:3b)")
    ap.add_argument("--stub", action="store_true", help="keyword planner, no model")
    ap.add_argument("--freeze", action="store_true",
                    help="recompute expected values from the verified specs")
    ap.add_argument("--out", help="write a markdown report here")
    a = ap.parse_args()

    cases = yaml.safe_load(GOLDEN.read_text())
    # follow-ups must run after the turn they depend on
    cases.sort(key=lambda c: 1 if c.get("after") else 0)

    if a.stub:
        from app.stub_planner import plan as planner
        label = "stub (keyword rules)"
    else:
        from app.planner import plan_detailed
        if a.model:
            from app.llm import set_model
            set_model("planner", a.model)
        from app.llm import MODELS
        planner, label = plan_detailed, MODELS["planner"]

    print(f"planner: {label}   cases: {len(cases)}\n")

    stats = collections.defaultdict(lambda: [0, 0])   # bucket -> [hits, total]
    failures, latencies, priors = [], [], {}

    for case in cases:
        cid, tags = case["id"], case.get("tags", ["untagged"])
        try:
            spec, ms = run_case(case, planner, priors)
            latencies.append(ms)
        except Exception as e:
            failures.append((cid, f"planner error: {type(e).__name__}: {e}"))
            for t in tags:
                stats[t][1] += 1
            stats["ALL"][1] += 1
            continue

        want_refusal = case.get("expect_refusal") or case.get("expect_clarification")
        ok, why = True, ""

        if want_refusal:
            ans = answer_spec(spec, case["question"])
            ok = ans.refused
            why = "answered when it should have declined"
        else:
            if "expect_spec" in case:
                # Compare the spec that actually executes. The validator resolves
                # "DMart" to the real vendor name, so judging the raw model output
                # marks a correct answer wrong.
                from app import validator as _v
                verdict = _v.validate(spec)
                effective = (verdict.repaired or spec) if verdict.ok else spec
                got = effective.model_dump(mode="json")
                # A question may have more than one defensible reading.
                wants = case.get("accept_any") or [case["expect_spec"]]
                ok = any(subset_match(got, w) for w in wants)
                why = (f"spec mismatch: wanted any of {wants}" if len(wants) > 1
                       else f"spec mismatch: wanted {case['expect_spec']}")
            if ok and "expected_value" in case:
                ans = answer_spec(spec, case["question"])
                got = metric_value(ans)
                exp = case["expected_value"]
                isnan = lambda v: isinstance(v, float) and v != v   # noqa: E731
                got = None if isnan(got) else got
                exp = None if isnan(exp) else exp
                ok = (got is None and exp is None) or (
                    got is not None and exp is not None and abs(got - exp) < 0.01)
                why = f"value {got} != {exp}"

        for t in tags + ["ALL"]:
            stats[t][0] += ok
            stats[t][1] += 1
        if not ok:
            failures.append((cid, why))

    if a.freeze:
        freeze(cases)
        return

    lines = [f"### Accuracy — planner `{label}`", "",
             "| bucket | correct | total | % |", "|---|---:|---:|---:|"]
    for bucket in sorted(stats, key=lambda b: (b != "ALL", b)):
        hit, tot = stats[bucket]
        lines.append(f"| {bucket} | {hit} | {tot} | {100*hit/tot:.0f}% |")
    if latencies:
        lines += ["", f"planner latency: p50 {1000*sorted(latencies)[len(latencies)//2]:.0f}ms, "
                      f"max {1000*max(latencies):.0f}ms"]
    if failures:
        lines += ["", "### Failures", ""]
        lines += [f"- `{cid}` — {why}" for cid, why in failures]

    report = "\n".join(lines)
    print(report)
    if a.out:
        pathlib.Path(a.out).write_text(report + "\n")
        print(f"\nwrote {a.out}")

    try:
        from app.llm import efficiency_report
        r = efficiency_report()
        if r["calls"]:
            print(f"\nmodel efficiency: {r}")
    except Exception:
        pass


def freeze(cases):
    """Derive expected values by running each hand-verified spec. Nobody hand
    computes a sum; the human only checks that the interpretation is right."""
    out, skipped = [], 0
    for case in cases:
        if "expect_spec" not in case or case.get("expect_refusal"):
            out.append(case); continue
        try:
            ans = answer_spec(QuerySpec(**case["expect_spec"]), case["question"])
            case["expected_value"] = metric_value(ans)
        except Exception as e:
            print(f"  {case['id']}: could not freeze ({type(e).__name__}: {e})")
            skipped += 1
        out.append(case)
    GOLDEN.write_text(yaml.safe_dump(out, sort_keys=False, width=100, allow_unicode=True))
    print(f"froze expected values for {len(out) - skipped} cases "
          f"({skipped} skipped) -> {GOLDEN.name}")
    print("Review the diff before committing: a wrong spec freezes a wrong number.")


if __name__ == "__main__":
    main()
