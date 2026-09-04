"""Accuracy harness. Run after every merge -- `make eval`.

Scores three things separately, because they fail for different reasons:
  spec accuracy   -- did the planner understand the question?
  value accuracy  -- did the pipeline compute the right number?
  refusal accuracy -- did it decline when it should have?
"""
import pathlib, sys, yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

GOLDEN = yaml.safe_load((pathlib.Path(__file__).parent / "golden.yaml").read_text())


def main():
    from app.planner import plan
    from app.api import answer_spec

    stats = {"spec": [0, 0], "value": [0, 0], "refusal": [0, 0]}
    failures = []

    for case in GOLDEN:
        try:
            spec = plan(case["question"])
        except NotImplementedError:
            print("planner not wired yet -- nothing to evaluate"); return
        except Exception as e:
            failures.append((case["id"], f"planner error: {e}")); continue

        if case.get("expect_refusal") or case.get("expect_clarification"):
            stats["refusal"][1] += 1
            res = answer_spec(spec, case["question"])
            if res.refused:
                stats["refusal"][0] += 1
            else:
                failures.append((case["id"], "answered when it should have refused"))
            continue

        if "expect_spec" in case:
            stats["spec"][1] += 1
            want = case["expect_spec"]
            got = spec.model_dump()
            if all(_match(got.get(k), v) for k, v in want.items()):
                stats["spec"][0] += 1
            else:
                failures.append((case["id"], f"spec mismatch: {want}"))

        if case.get("expect_value") is not None:
            stats["value"][1] += 1
            res = answer_spec(spec, case["question"])
            actual = res.breakdown[0].get(spec.metric) if res.breakdown else None
            if actual is not None and abs(actual - case["expect_value"]) < 0.01:
                stats["value"][0] += 1
            else:
                failures.append((case["id"], f"value {actual} != {case['expect_value']}"))

    print("\n=== accuracy ===")
    for k, (hit, total) in stats.items():
        pct = f"{100*hit/total:.0f}%" if total else "n/a"
        print(f"  {k:9} {hit}/{total}  {pct}")

    if failures:
        print("\n=== failures ===")
        for cid, why in failures:
            print(f"  {cid}: {why}")

    try:
        from app.llm import efficiency_report
        print("\n=== model efficiency ===\n ", efficiency_report())
    except Exception:
        pass


def _match(got, want):
    if isinstance(want, dict) and isinstance(got, dict):
        return all(_match(got.get(k), v) for k, v in want.items())
    return got == want


if __name__ == "__main__":
    main()
