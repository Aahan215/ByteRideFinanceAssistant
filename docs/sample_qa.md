# Sample Q&A

Real transcripts from the running assistant — the prose answer, SQL, breakdown,
evidence, confidence, and model routing for each question are recorded
verbatim, as returned by `POST /ask`. Nothing below is hand-edited; where an
answer is wrong or awkward, it is kept as-is with a one-line **Note** under it.

Run conditions: `./.venv/bin/uvicorn app.api:app --port 8791`, Ollama local
with `qwen3:4b` as the planner tier and `qwen3:8b` as the escalation tier,
`data/finance.duckdb` loaded, anchor date **2026-06-30** (confirmed via
`GET /health`).

---

## 1. "How much did I spend last month?"

**Answer:** Total for 2026-05-01 to 2026-05-31: ₹1,62,50,89,107.

**Confidence:** high — **model_used:** `qwen3:4b` — **escalated:** false

```sql
SELECT SUM(transaction_amount) AS sum_amount FROM txn_enriched
WHERE transaction_type = 'debit' AND transaction_date >= ? AND transaction_date < ?
ORDER BY sum_amount DESC LIMIT 50
```

| sum_amount |
|---|
| 1625089107.26 |

**Evidence rows:** 25 (excerpt below)

| transaction_date | description | amount | account_number | utr_number |
|---|---|---|---|---|
| 2026-05-31T23:58:33 | IMPS/P2A/S955206729/UBIN/.../APOLLO PHARMACY T NAGAR CHENNAI | 32493.0 | XXXXXX1922 | null |
| 2026-05-31T23:47:04 | FT - S312460746 - ... - SPENCERS RETAIL LTD | 10000.0 | XXXXXX3894 | [redacted] |
| 2026-05-31T23:41:53 | MSEB ELECTRICITY NA | 2534.56 | XXXXXX2233 | null |

**Anomalies:**
- BIG BAZAAR RETAIL: ₹1,13,84,825 is 1357x the usual ₹8,387 across 8,354 past transactions
- RENT PAYMENT PRIYA SHARMA: ₹60,947 is 5x the usual ₹11,170 across 205 past transactions
- RENT PAYMENT DEEPA AGARWAL: ₹65,370 is 6x the usual ₹11,125 across 267 past transactions

**Warnings:** `Read "last month" as 2026-05-01 to 2026-05-31.`

**Latency:** 1.62s

---

## 2. "Which vendors did I pay the most last month?"

**Answer:** Across 10 vendors for 2026-05-01 to 2026-05-31, EMI BAJAJ FINANCE is highest at ₹13,73,25,576. Followed by LIC PREMIUM POLICY at ₹3,03,80,709.

**Confidence:** high — **model_used:** `qwen3:4b` — **escalated:** false

```sql
SELECT counterparty AS counterparty, SUM(transaction_amount) AS sum_amount FROM txn_enriched
WHERE transaction_type = 'debit' AND counterparty IS NOT NULL
  AND transaction_date >= ? AND transaction_date < ?
GROUP BY counterparty ORDER BY sum_amount DESC LIMIT 10
```

| counterparty | sum_amount |
|---|---|
| EMI BAJAJ FINANCE | 137325576.24 |
| LIC PREMIUM POLICY | 30380708.88 |
| BIG BAZAAR RETAIL | 19546488.26 |
| GROWW MUTUAL FUND SIP | 17810392.74 |
| ZERODHA BROKING | 17661813.11 |
| UPSTOX | 17525318.23 |
| SIP HDFC MF | 17507918.08 |
| BHARAT PETROLEUM OUTLET | 11630413.74 |
| SHREE BALAJI TRADERS | 11520077.78 |
| SELECTION ELECTRONICS | 11421555.02 |

**Evidence rows:** 25 (excerpt below)

| transaction_date | description | amount | account_number | utr_number |
|---|---|---|---|---|
| 2026-05-31T23:58:33 | IMPS/P2A/S955206729/UBIN/.../APOLLO PHARMACY T NAGAR CHENNAI | 32493.0 | XXXXXX1922 | null |
| 2026-05-31T23:47:04 | FT - S312460746 - ... - SPENCERS RETAIL LTD | 10000.0 | XXXXXX3894 | [redacted] |
| 2026-05-31T23:41:53 | MSEB ELECTRICITY NA | 2534.56 | XXXXXX2233 | null |

**Anomalies:** same three as Q1 (BIG BAZAAR RETAIL, RENT PAYMENT PRIYA SHARMA, RENT PAYMENT DEEPA AGARWAL).

**Warnings:**
- `₹40,30,21,720 across 23,993 transactions has no counterparty at all (tax, bank charges and cash have no payee), so it is correctly outside a counterparty breakdown.`
- `Read "last month" as 2026-05-01 to 2026-05-31.`

**Latency:** 1.65s

---

## 3. "How does that compare with the month before?" (multiturn, same session_id as Q2)

**Answer:** Across 10 vendors for 2026-05-01 to 2026-05-31, EMI BAJAJ FINANCE is highest at ₹13,73,25,576. Followed by LIC PREMIUM POLICY at ₹3,03,80,709. Compared with 2026-04-01 to 2026-04-30, the biggest move is BIG BAZAAR RETAIL, up ₹1,13,26,049.

**Confidence:** high — **model_used:** `qwen3:4b` — **escalated:** false

The follow-up carried no dataset/metric/group_by in its own text — the SQL executed is the same grouped-by-vendor query as Q2, re-resolved from session context, plus a second run against the prior month for the diff:

```sql
SELECT counterparty AS counterparty, SUM(transaction_amount) AS sum_amount FROM txn_enriched
WHERE transaction_type = 'debit' AND counterparty IS NOT NULL
  AND transaction_date >= ? AND transaction_date < ?
GROUP BY counterparty ORDER BY sum_amount DESC LIMIT 10
```

**Breakdown (top 10, same as Q2):** unchanged from above.

**Comparison (`comparison.rows`, top of list, sorted by |delta|):**

| counterparty | value (May) | previous (Apr) | delta | delta_pct |
|---|---|---|---|---|
| BIG BAZAAR RETAIL | 19546488.26 | 8220438.81 | 11326049.45 | 137.8% |
| UMANG SELECTION | 10607848.50 | 7740565.77 | 2867282.73 | 37.0% |
| NEHA RAO | 3405600.77 | 1334846.29 | 2070754.48 | 155.1% |
| NILGIRIS SUPERMARKET SAKET DELHI | 2500783.93 | 501613.87 | 1999170.06 | 398.5% |
| MOHAMMED VERMA | 3253756.94 | 1315573.60 | 1938183.34 | 147.3% |
| STAR COMMUNICATION KORAMANGALA | 587231.35 | 3226205.68 | -2638974.33 | -81.8% |
| ARJUN KUMAR | 667566.37 | 2722390.28 | -2054823.91 | -75.5% |
| MOHAMMED NAIR | 1686230.26 | 3613785.43 | -1927555.17 | -53.3% |
| GANESH MOBILE WORLD | 5007998.41 | 6818629.27 | -1810630.86 | -26.6% |

This confirms the "no context repeated" claim from `TEAM.md`'s demo script: the follow-up question contained none of the original filters, dataset, or grouping, yet the server correctly re-ran the vendor breakdown from `session_id=s2` and diffed it against the prior month.

**Evidence rows:** 25. **Anomalies:** same three as Q1/Q2.

**Warnings:** `₹40,30,21,720 across 23,993 transactions has no counterparty at all (tax, bank charges and cash have no payee), so it is correctly outside a counterparty breakdown.`

**Latency:** 1.77s

---

## 4. "How much tax did I pay this year?"

**Answer:** Total for 2026-01-01 to 2026-12-31: ₹1,95,63,10,950.

**Confidence:** high — **model_used:** `qwen3:4b` — **escalated:** false

```sql
SELECT SUM(transaction_amount) AS sum_amount FROM txn_enriched
WHERE transaction_type = 'debit' AND category = ?
  AND transaction_date >= ? AND transaction_date < ?
ORDER BY sum_amount DESC LIMIT 50
```

| sum_amount |
|---|
| 1956310950.38 |

**Evidence rows:** 25 (excerpt below)

| transaction_date | description | amount | account_number | utr_number |
|---|---|---|---|---|
| 2026-06-30T23:43:47 | CGST S963582451 | 16656.37 | XXXXXX7265 | [redacted] |
| 2026-06-30T22:58:13 | GST PAYMENT CHALLAN S816743051 | 50000.0 | XXXXXX1419 | [redacted] |
| 2026-06-30T22:57:22 | CGST S616353915 | 26462.48 | XXXXXX9875 | [redacted] |

**Anomalies:** none. **Warnings:** `Read "this year" as 2026-01-01 to 2026-12-31.`

TAX here is a derived category (GST/CGST/IGST challans, tax narrations), not a line from a filing — consistent with the demo script's "derived category, shown as derived."

**Latency:** 1.55s

---

## 5. "Which transactions are unreconciled?" — the key refusal

**Answer:** This dataset has no reconciliation status. The transaction table records id, date, type, description, amount and reference numbers -- there is no field saying whether a transaction was matched to an external record, and I will not infer one. I can show transactions with or without a reference number if that helps.

**Confidence:** n/a — **model_used:** null — **escalated:** false — **refused:** true

**SQL:** none run. **Breakdown / evidence:** empty. **Anomalies / warnings:** none.

**Latency:** 0.007s — this refusal is fast enough that it does not appear to touch the LLM at all; it reads as a static/keyword-level guard ("reconciled/reconciliation" has no backing column) rather than a round trip to Ollama. This is the demo's "money shot": the assistant declines cleanly instead of fabricating a reconciliation status the data cannot support.

---

## 6. "What is my average payment to Zomato Hyperpure?"

**Answer:** Average for all time: ₹15,647.

**Confidence:** high — **model_used:** `qwen3:4b` — **escalated:** false

```sql
SELECT AVG(transaction_amount) AS avg_amount FROM txn_enriched
WHERE transaction_type = 'debit' AND counterparty IN (?, ?, ?, ?, ?, ?, ?, ?)
ORDER BY avg_amount DESC LIMIT 50
```

| avg_amount |
|---|
| 15647.380914071511 |

**Evidence rows:** 25 (excerpt below)

| transaction_date | description | amount | account_number | utr_number |
|---|---|---|---|---|
| 2026-06-30T23:58:24 | UPI-ZOMATO HYPERPURE-XXXXXX2946-UTIB0799917-S779607690 | 39098.0 | XXXXXX7433 | null |
| 2026-06-30T20:54:43 | NEFT - AUBL0712045 - S100358339 - ... - ZOMATO HYPERPURE | 5000.0 | XXXXXX2369 | null |
| 2026-06-30T20:40:45 | UPI-ZOMATO HYPERPURE-XXXXXX6890-UBIN0861673-S420521169 | 18441.0 | XXXXXX4482 | [redacted] |

**Anomalies:**
- ZOMATO HYPERPURE ANDHERI WEST: ₹9,99,780 is 100x the usual ₹10,000 across 458 past transactions
- ZOMATO HYPERPURE SAKET DELHI: ₹6,84,031 is 68x the usual ₹10,000 across 476 past transactions
- ZOMATO HYPERPURE: ₹6,97,246 is 83x the usual ₹8,365 across 7,674 past transactions

**Warnings:** `'ZOMATO HYPERPURE' matched 8 vendor names that look like the same merchant, and all are included: ZOMATO HYPERPURE, ZOMATO HYPERPURE ANDHERI WEST, ZOMATO HYPERPURE DAHISAR EAST, ZOMATO HYPERPURE HINJEWADI PUNE, ZOMATO HYPERPURE KORAMANGALA, ZOMATO HYPERPURE SAKET DELHI, ZOMATO HYPERPURE SALT LAKE KOLKATA, ZOMATO HYPERPURE T NAGAR CHENNAI.`

**Latency:** 1.97s

---

## 7. "How much did I pay Northwind Traders?" (ambiguous vendor, `evals/golden.yaml` id `amb_unknown_vendor`)

**Answer:** I have no vendor matching 'NORTHWIND TRADERS' in this dataset.

**Confidence:** n/a — **model_used:** `qwen3:4b` — **escalated:** false — **refused:** true

**SQL:** none. `clarification`: null. `suggestions`: [].

**Latency:** 1.62s

**Note:** `evals/golden.yaml` tags this question `ambiguous` with `expect_refusal: true`, which is satisfied (`refused: true`). But it is a flat "no such vendor" refusal, not a clarification prompt — `clarification` and `suggestions` are both empty because "NORTHWIND TRADERS" has zero close string matches against known vendor names. The app's real clarification path (populated `clarification` + clickable `suggestions`) fires only when a name is a genuine partial match across multiple distinct vendors — e.g. asking "How much did I pay Mohammed?" against this data returns `clarification: "I have several vendors matching 'MOHAMMED'. Which did you mean?"` with suggestions `["How much did I pay MOHAMMED?", "...MOHAMMED AGARWAL?", "...MOHAMMED BHATT?", "...MOHAMMED CHATTERJEE?", "...MOHAMMED DESAI?"]`. None of the three `ambiguous`-tagged golden questions ("Northwind Traders", "travel", bare "spend") happen to hit that path — they are all "term does not exist at all" refusals.

---

## 8. "How many payments over 1 lakh did I make in May?"

**Answer:** Count for 2026-05-01 to 2026-05-31: 475.

**Confidence:** high — **model_used:** `qwen3:4b` — **escalated:** false

```sql
SELECT COUNT(*) AS count FROM txn_enriched
WHERE transaction_amount >= ? AND transaction_amount <= ? AND transaction_date >= ? AND transaction_date < ?
ORDER BY count DESC LIMIT 50
```

| count |
|---|
| 475 |

**Evidence rows:** 25 (excerpt below)

| transaction_date | description | amount | account_number | utr_number |
|---|---|---|---|---|
| 2026-05-31T20:11:51 | FT - S324828466 - ... - LENSKART SOLUTIONS | 100000.0 | XXXXXX4737 | null |
| 2026-05-31T13:53:58 | Cheque Deposits S157943111 | 100000.0 | XXXXXX5386 | [redacted] |
| 2026-05-31T07:44:35 | IMPS OW/S133119407/ANITA RAO/CNRB/15756077414347 | 100000.0 | XXXXXX4374 | null |

**Anomalies:** none. **Warnings:** `Read "in may" as 2026-05-01 to 2026-05-31.`

**Latency:** 2.26s

**Note:** the planner does not resolve "lakh" (100000) as an amount unit and refuses outright, even though the underlying `QuerySpec` supports a `min_amount` filter combined with `count`. Rephrasing with the numeric threshold works partially — `"How many payments over 100000 did I make in May?"` returns `Count for all time: 7,657` with SQL `SELECT COUNT(*) AS count FROM txn_enriched WHERE transaction_amount >= ? AND transaction_amount <= ? ORDER BY count DESC LIMIT 50` — but the "in May" date filter is silently dropped (the answer is scoped "for all time", not to May), so the filter+count combination is not fully reliable in either phrasing.

---

## Efficiency and boundary reports

`GET /efficiency` (taken after all questions above, including a few exploratory probes run while investigating the ambiguous-question and amount-filter behavior for Q7/Q8):

```json
{
  "endpoint": "http://localhost:11434/v1",
  "calls": 17,
  "escalations": 0,
  "escalation_rate": 0.0,
  "by_model": {
    "qwen3:4b": 17
  }
}
```

All 17 planner calls in this run were handled by `qwen3:4b`; the escalation tier (`qwen3:8b`) was never needed.

`GET /boundary` confirms the data/model boundary: `"rule": "the model receives the question and the schema; never a data row"`, `"narrator_sends_results_to_model": false`, 17 crossings, all role `"planner"`, ~89KB of schema+question text sent to Ollama total — no transaction rows, account numbers, or amounts appear in what was sent to the model.

---

## How to reproduce

```bash
./.venv/bin/uvicorn app.api:app --port 8791
```

Example request:

```bash
curl -s -X POST http://127.0.0.1:8791/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which vendors did I pay the most last month?","session_id":"demo"}'
```

Then, for the same conversation:

```bash
curl -s -X POST http://127.0.0.1:8791/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"How does that compare with the month before?","session_id":"demo"}'
```

`GET /efficiency` and `GET /boundary` take no body and report cumulative stats for the server's lifetime.
