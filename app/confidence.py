"""Confidence signalling.

The problem statement asks the assistant to flag when it is less certain
"instead of stating everything with equal confidence". A model's own claim
about its confidence is not evidence, so this combines signals we can actually
observe -- most of them deterministic, so confidence still works when the model
is unavailable:

  * planner self-consistency   did the model agree with itself across samples
  * fuzzy matching             did we have to guess which vendor was meant
  * data coverage              how much spend has no counterparty to attribute
  * sample size                an aggregate over 6 rows is not a trend
  * comparison validity        are the two periods the same length

Each downgrade carries a REASON. A bare "medium" badge tells a user nothing;
"medium - 29% of spend in this period has no identifiable vendor" tells them
exactly how much to trust the ranking and why.
"""
from __future__ import annotations
from dataclasses import dataclass, field

SMALL_SAMPLE = 10            # below this, "usual" and "top" are not real claims
COVERAGE_CONCERN = 0.20      # >20% unattributed spend materially skews a ranking


@dataclass
class Assessment:
    level: str = "high"      # high | medium | low
    reasons: list[str] = field(default_factory=list)

    def downgrade(self, to: str, reason: str) -> None:
        order = {"high": 0, "medium": 1, "low": 2}
        if order[to] > order[self.level]:
            self.level = to
        self.reasons.append(reason)


def assess(*, spec, row_count: int | None = None, excluded_rows: int = 0,
           unattributed_rows: int = 0,
           warnings: list[str] | None = None, planner_confidence: str | None = None,
           comparison_mismatch: bool = False) -> Assessment:
    a = Assessment()
    warnings = warnings or []

    # The model disagreeing with itself is the strongest single signal.
    if planner_confidence == "low":
        a.downgrade("low", "the model produced different interpretations of this question")
    elif planner_confidence == "medium":
        a.downgrade("medium", "the model was not fully consistent in interpreting this question")

    if any(w.startswith("Interpreted ") for w in warnings):
        a.downgrade("medium", "a name in your question was matched approximately")

    if row_count is not None:
        if row_count == 0:
            return Assessment("n/a", ["no matching transactions"])
        if row_count < SMALL_SAMPLE:
            a.downgrade("medium", f"based on only {row_count} transaction"
                                  f"{'s' if row_count != 1 else ''}")

    if spec.group_by and row_count:
        # Rows that legitimately have no value for this dimension (tax has no
        # payee) are correctly excluded, not a gap. Measuring them as one
        # flagged nearly every vendor question as medium confidence for a
        # ranking that was in fact complete.
        share = unattributed_rows / (row_count + unattributed_rows)
        if share > COVERAGE_CONCERN:
            a.downgrade("medium",
                        f"{share:.0%} of matching transactions have a "
                        f"{spec.group_by[0]} we could not extract from the "
                        f"narration, so this ranking is incomplete")

    if comparison_mismatch:
        a.downgrade("medium", "the two periods compared are different lengths")

    # Escalate only when 3+ independent concerns stack up.
    if a.level == "medium" and len(a.reasons) >= 3:
        a.level = "low"
    return a
