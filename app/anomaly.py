"""Anomaly callouts: "that payout looks unusually large for this vendor".

Method: robust statistics on LOG amounts, per counterparty.

Why not a plain z-score on the raw amount: transaction values are roughly
log-normal, so mean+stddev is dragged around by the very outliers we are
hunting and flags a third of ordinary merchant payments. Median plus MAD
(median absolute deviation) in log space is unmoved by outliers and treats a
10x payment as 10x regardless of the vendor's typical size.

Everything here is deterministic and precomputed. The model is never asked
whether a number looks unusual.
"""
from __future__ import annotations
from dataclasses import dataclass

# 0.6745 rescales MAD so the score reads like a normal-distribution z-score.
MAD_TO_SIGMA = 0.6745
THRESHOLD = 3.5          # conservative: a callout that cries wolf is worse than none

# The brief asks us to flag a payout that looks "unusually large". Small
# outliers are real but far less interesting -- a failed or test payment -- and
# mixing them in dilutes the callout. Set to False to surface both.
HIGH_SIDE_ONLY = True

# A robust score alone ranked "3x the usual rent" above a 357x merchant payment.
# Statistically that is right -- rent is near-constant, so 3x is genuinely
# surprising -- but "unusually large" should also LOOK large to the reader.
# Requiring a material multiple on top of the score keeps the statistics and
# drops callouts nobody would act on.
MIN_MULTIPLE = 5.0
MIN_HISTORY = 20         # below this, "usual for this vendor" is not a real claim
FLAT_TOLERANCE = 0.5     # for fixed-amount vendors (EMI, rent) where MAD == 0


@dataclass
class Flag:
    counterparty: str
    amount: float
    typical: float
    score: float
    direction: str        # "high" | "low"
    n: int

    def sentence(self) -> str:
        from app.narrator import inr          # one currency format across the app

        seen = f"across {self.n:,} past transactions"
        # `not nan` is False, so a NaN typical slipped past the guard below and
        # the division produced a NaN multiple.
        bad = [v for v in (self.amount, self.typical)
               if v is None or (isinstance(v, float) and v != v)]
        if bad:
            return f"{self.counterparty}: {inr(self.amount)} ({seen})"
        if not self.typical:
            return f"{self.counterparty}: {inr(self.amount)} ({seen})"
        if self.direction == "high":
            return (f"{self.counterparty}: {inr(self.amount)} is "
                    f"{self.amount / self.typical:.0f}x the usual "
                    f"{inr(self.typical)} {seen}")
        # "0.0x the usual" is not a sentence anyone can act on. Say how much
        # SMALLER it is, in the same shape as the high-side wording.
        return (f"{self.counterparty}: {inr(self.amount)} is "
                f"{self.typical / self.amount:.0f}x smaller than the usual "
                f"{inr(self.typical)} {seen}")


STATS_SQL = """
CREATE OR REPLACE TABLE counterparty_stats AS
SELECT counterparty,
       COUNT(*)                                      AS n,
       median(ln(transaction_amount))                AS median_log,
       -- MAD: median of absolute deviations from the median, in log space
       median(abs(ln(transaction_amount)
                  - (SELECT median(ln(t2.transaction_amount))
                     FROM txn_enriched t2
                     WHERE t2.counterparty = t1.counterparty
                       AND t2.transaction_amount > 0)))  AS mad_log,
       exp(median(ln(transaction_amount)))           AS typical_amount
FROM txn_enriched t1
WHERE counterparty IS NOT NULL AND transaction_amount > 0
GROUP BY counterparty
HAVING COUNT(*) >= {min_history}
"""


def build_stats_sql(min_history: int = MIN_HISTORY) -> str:
    return STATS_SQL.format(min_history=min_history)


def score_row(amount: float, median_log: float, mad_log: float) -> tuple[float, str]:
    """Robust z-score in log space. Returns (score, direction)."""
    import math
    if amount is None or amount <= 0:
        return 0.0, "high"
    x = math.log(amount)
    dev = x - median_log
    direction = "high" if dev >= 0 else "low"
    if mad_log and mad_log > 1e-9:
        return abs(MAD_TO_SIGMA * dev / mad_log), direction
    # MAD == 0 means this vendor always charges the same (EMI, rent, subscription).
    # Any real deviation there is meaningful, but scale it so it is comparable.
    return (abs(dev) / FLAT_TOLERANCE, direction) if abs(dev) > FLAT_TOLERANCE else (0.0, direction)


def score_sql(amount: str = "t.transaction_amount") -> str:
    """The same robust score, as SQL.

    Generated from the constants above rather than written out, so the Python
    and SQL implementations cannot drift apart.
    """
    dev = f"(ln({amount}) - s.median_log)"
    return (f"CASE WHEN s.mad_log > 1e-9 "
            f"THEN abs({MAD_TO_SIGMA} * {dev} / s.mad_log) "
            f"WHEN abs({dev}) > {FLAT_TOLERANCE} "
            f"THEN abs({dev}) / {FLAT_TOLERANCE} ELSE 0 END")


def scan_sql(where: list[str], view: str, limit: int = 3,
             threshold: float = THRESHOLD) -> str:
    """Scan EVERY row the answer covers, not just the page of evidence rows.

    Outliers are rare by definition -- roughly 0.1% of transactions -- so
    scanning only the most recent 200 records finds nothing almost every time.
    One extra aggregate over the same filtered window costs tens of
    milliseconds and makes the feature actually work.
    """
    clause = (" WHERE " + " AND ".join(where + ["t.transaction_amount > 0"])
              if where else " WHERE t.transaction_amount > 0")
    # A subquery, not QUALIFY: QUALIFY filters window-function results and
    # `score` is a plain expression.
    inner = (f"SELECT t.counterparty, t.transaction_amount, t.transaction_date, "
             f"s.typical_amount, s.n, {score_sql()} AS score "
             f"FROM {view} t JOIN counterparty_stats s USING (counterparty){clause}")
    return (f"SELECT * FROM ({inner}) WHERE score >= {threshold} "
            f"ORDER BY score DESC LIMIT {limit * 4}")


def from_scan(df, limit: int = 3, high_only: bool = HIGH_SIDE_ONLY) -> list[Flag]:
    """Turn scan rows into flags, one per counterparty."""
    if df is None or df.empty:
        return []
    seen, out = set(), []
    for r in df.itertuples():
        if r.counterparty in seen:
            continue
        direction = "high" if r.transaction_amount >= r.typical_amount else "low"
        if high_only and direction != "high":
            continue
        if r.typical_amount and direction == "high" \
                and r.transaction_amount / r.typical_amount < MIN_MULTIPLE:
            continue
        seen.add(r.counterparty)
        out.append(Flag(r.counterparty, float(r.transaction_amount),
                        float(r.typical_amount), float(r.score), direction, int(r.n)))
        if len(out) >= limit:
            break
    return out


def find(evidence_df, stats_df, threshold: float = THRESHOLD, limit: int = 3) -> list[Flag]:
    """Python-side equivalent of the scan, used in tests and as a fallback."""
    if evidence_df is None or evidence_df.empty or stats_df is None or stats_df.empty:
        return []
    stats = {r.counterparty: r for r in stats_df.itertuples()}
    flags = []
    for row in evidence_df.itertuples():
        cp = getattr(row, "counterparty", None)
        amt = getattr(row, "transaction_amount", None)
        st = stats.get(cp)
        if not st or amt is None:
            continue
        s, direction = score_row(float(amt), st.median_log, st.mad_log)
        if s >= threshold:
            flags.append(Flag(cp, float(amt), float(st.typical_amount), s, direction, int(st.n)))
    flags.sort(key=lambda f: f.score, reverse=True)
    # one callout per vendor -- three rows from the same vendor is one story
    seen, out = set(), []
    for f in flags:
        if f.counterparty in seen:
            continue
        seen.add(f.counterparty)
        out.append(f)
        if len(out) >= limit:
            break
    return out
