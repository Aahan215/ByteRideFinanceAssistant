"""Accuracy harness. `make eval`.

Scores three things separately, because they fail for different reasons:

  spec  -- did the planner understand the question?
  value -- did the pipeline compute the same number the verified spec gives?
  refusal -- did it decline when the data cannot answer?

Expected VALUES are never hand-written. They are derived by running the
hand-verified `expect_spec` through the same engine, so a human only ever
checks an interpretation, never arithmetic.

    python evals/run_evals.py                      # tiered config, escalation on
    python evals/run_evals.py --model qwen2.5:3b   # single-model comparison,
                                                    #   escalation forced off so
                                                    #   the table shows the raw
                                                    #   model, not the pipeline
    python evals/run_evals.py --model qwen3:4b --escalate-model qwen3:8b
                                                    # explicit tiered comparison
    python evals/run_evals.py --samples 3           # override confidence.samples
                                                    #   for this run only
    python evals/run_evals.py --stub               # no model at all
    python evals/run_evals.py --out report.md      # markdown for the deck

Every non-stub case is planned through `app.planner.plan_with_confidence` --
the SAME function `/ask` calls -- so this harness actually exercises
self-consistency sampling and confidence-ratio escalation, not just the raw
per-model planner (`plan_detailed`, which skips both).
"""
from __future__ import annotations
import argparse, collections, os, pathlib, sys, time

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
    # --stub returns a bare QuerySpec (no model attribution at all), and
    # plan_with_confidence/plan_detailed report model_used=None for a refusal
    # decided before any model call (out-of-scope, a contentless question).
    # Both are genuinely "no model was consulted" -- label them the same,
    # rather than calling a real planner's deterministic refusal "stub",
    # which it is not.
    model_used = getattr(result, "model_used", None) or "none (no model call)"
    escalated = bool(getattr(result, "escalated", False))
    # --stub has no confidence signal at all (no self-consistency sampling);
    # "n/a" is honest, not a fourth confidence LEVEL.
    confidence = getattr(result, "confidence", "n/a") or "n/a"
    priors[case["id"]] = spec
    return spec, latency, model_used, escalated, confidence


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", help="override the planner model for a single-model "
                                    "comparison (e.g. qwen2.5:3b); this also turns "
                                    "escalation OFF so the table reflects that model "
                                    "alone, not the tiered pipeline -- pass "
                                    "--escalate-model too to compare tiered configs")
    ap.add_argument("--escalate-model", help="override the escalate model; combine "
                                             "with --model to run an explicit tiered "
                                             "comparison instead of a single-model one")
    ap.add_argument("--stub", action="store_true", help="keyword planner, no model")
    ap.add_argument("--samples", type=int, help="override confidence.samples "
                                                "(config/models.yaml) for this run, "
                                                "via FINANCE_CONFIDENCE_SAMPLES")
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
        escalation_note = "n/a"
        samples_note = "n/a"
    else:
        # The SAME function /ask calls -- plan_detailed alone never samples
        # and never triggers the confidence-ratio escalation trigger, so an
        # eval built on it could not exercise either one (see module docstring).
        from app.planner import plan_with_confidence, confidence_samples
        from app.llm import set_model, MODELS, CFG
        if a.model:
            set_model("planner", a.model)
            if not a.escalate_model:
                # A single-model comparison should show what THAT model does,
                # not the tiered pipeline quietly bailing it out -- see M6.
                os.environ["FINANCE_ESCALATE"] = "0"
        if a.escalate_model:
            set_model("escalate", a.escalate_model)
            # An explicit tiered comparison always wants escalation on, even if
            # the shell has FINANCE_ESCALATE=0 set from a prior single-model run.
            os.environ["FINANCE_ESCALATE"] = "1"
        if a.samples is not None:
            os.environ["FINANCE_CONFIDENCE_SAMPLES"] = str(a.samples)
        planner, label = plan_with_confidence, MODELS["planner"]
        escalation_note = ("disabled (--model without --escalate-model)"
                           if os.getenv("FINANCE_ESCALATE") == "0"
                           else f"on -> {MODELS['escalate']}")
        samples_note = confidence_samples(CFG.get("confidence", {}).get("samples", 1))

    print(f"planner: {label}   escalate: {escalation_note}   "
          f"confidence samples: {samples_note}   cases: {len(cases)}\n")

    stats = collections.defaultdict(lambda: [0, 0])   # bucket -> [hits, total]
    failures, latencies, priors = [], [], {}
    # model attribution: model name -> [answered, correct]; escalated vs not -> [answered, correct]
    model_usage = collections.defaultdict(lambda: [0, 0])
    by_escalation = {True: [0, 0], False: [0, 0]}
    confidence_counts = collections.Counter()

    for case in cases:
        cid, tags = case["id"], case.get("tags", ["untagged"])
        try:
            spec, ms, model_used, escalated, conf_label = run_case(case, planner, priors)
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
            # VALUE check, computed live. Build the reference spec from the
            # verified expect_spec, inheriting everything the case does not pin
            # from the planner's own spec (a follow-up's window comes from the
            # prior turn; accept_any leaves the metric open). Then run BOTH
            # through the same engine on the same data and compare. Nothing is
            # frozen, so nothing goes stale.
            if ok and "expect_spec" in case and not case.get("accept_any"):
                ref = spec.model_copy(deep=True)
                ref_dict = ref.model_dump()
                for k, v in case["expect_spec"].items():
                    if k == "filters":
                        for fk, fv in v.items():
                            # Keep the planner's RESOLVED value when it already
                            # satisfies the expectation -- "DMart" resolved to a
                            # family containing the canonical name, and re-pinning
                            # the raw string threw that resolution away.
                            if not subset_match(ref_dict["filters"].get(fk), fv):
                                ref_dict["filters"][fk] = fv
                    else:
                        ref_dict[k] = v
                try:
                    ref = QuerySpec(**ref_dict)
                    got = metric_value(answer_spec(spec, case["question"]))
                    exp = metric_value(answer_spec(ref, case["question"]))
                except Exception as e:  # noqa: BLE001
                    got, exp = f"error {type(e).__name__}", None
                isnan = lambda v: isinstance(v, float) and v != v   # noqa: E731
                got = None if isnan(got) else got
                exp = None if isnan(exp) else exp
                same = (got is None and exp is None) or (
                    isinstance(got, (int, float)) and isinstance(exp, (int, float))
                    and abs(got - exp) < 0.01)
                if not same:
                    ok = False
                    why = f"value {got} != {exp} (live reference)"

        for t in tags + ["ALL"]:
            stats[t][0] += ok
            stats[t][1] += 1
        if not ok:
            failures.append((cid, why))

        model_usage[model_used][1] += 1
        model_usage[model_used][0] += ok
        by_escalation[escalated][1] += 1
        by_escalation[escalated][0] += ok
        confidence_counts[conf_label] += 1

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

    total_cases = sum(t for _, t in model_usage.values())
    if total_cases:
        lines += ["", "### Model usage", "",
                 "| model | cases | share | accuracy |", "|---|---:|---:|---:|"]
        for model, (hit, tot) in sorted(model_usage.items(), key=lambda kv: -kv[1][1]):
            lines.append(f"| {model} | {tot} | {100*tot/total_cases:.0f}% | "
                         f"{100*hit/tot:.0f}% |")
        esc_hit, esc_tot = by_escalation[True]
        plain_hit, plain_tot = by_escalation[False]
        lines += ["", f"escalation rate: {esc_tot}/{total_cases} "
                     f"({100*esc_tot/total_cases:.0f}%)"]
        if esc_tot and plain_tot:
            lines.append(f"accuracy — escalated: {100*esc_hit/esc_tot:.0f}% "
                         f"({esc_tot} cases), not escalated: "
                         f"{100*plain_hit/plain_tot:.0f}% ({plain_tot} cases)")

    conf_total = sum(confidence_counts.values())
    if conf_total:
        lines += ["", "### Confidence distribution", "",
                 "| confidence | cases | share |", "|---|---:|---:|"]
        for level in ("high", "medium", "low", "n/a"):
            c = confidence_counts.get(level, 0)
            if c:
                lines.append(f"| {level} | {c} | {100*c/conf_total:.0f}% |")

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
    """DEPRECATED and disabled. Frozen values go stale whenever the dataset is
    regenerated, and multi-turn cases were frozen without their prior turn.
    Values are now computed live at eval time from expect_spec."""
    sys.exit("`--freeze` is disabled: expected values are computed live from "
             "expect_spec at eval time. There is nothing to freeze.")


def _freeze_legacy(cases):
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
