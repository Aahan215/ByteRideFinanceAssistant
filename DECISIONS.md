# Open decisions — resolve these in the first hour

The real schema (`schema/DATA_DICTIONARY.md`) does not contain several things
the problem statement asks about. These are **judgement calls, not lookups.**
Each one needs an owner, a decision, and a line in the deck — judges will ask.

---

## 1. There is no reconciliation status column

The problem statement's second example question is *"Which transactions are
still unreconciled?"* The schema has no such column. Nothing to look up.

**Provisional definition (already implemented):** a transaction is reconciled
if it carries a `transaction_reference_id`; otherwise it is unreconciled — the
reasoning being that without a reference there is nothing to match against an
external record. Three of the ten sample rows have `NULL` here, so it produces
a real answer.

**Alternatives to consider:** derive from `available_balance` vs. the running
sum of transactions per account; or treat missing `utr_number` as the signal.

**Owner: Stream 1.** Whatever you pick, it lives in exactly one place —
`derived.reconciliation_state` in `semantic_layer.yaml` — and the UI must state
the definition on screen. An assistant that invents a reconciliation status is
exactly the failure mode this hackathon is testing for. Saying *"we define
unreconciled as X, here are those rows"* is a strength; silently implying the
data has a status field is a liability.

## 2. "Reference number" is ambiguous

`transaction_reference_id` is plaintext and searchable. `utr_number` is
sensitive and arrives already encrypted, so `WHERE utr_number = ?` cannot work
without decrypting rows first.

**Decided:** a bare "ref no" question hits `transaction_reference_id`. Only an
explicit "UTR" routes to `utr_number`, and that path must decrypt rather than
compare ciphertext. Encoded in `reference_columns` in the semantic layer.

## 3. There is no vendor table — vendors live inside free text

No `vendor_id`, no vendor list, no category, no chart of accounts. The
counterparty is embedded in narration strings. `app/enrich.py` parses it at
load time into a real column.

**Open sub-problem: trailing branch/location noise.** Right now
`SELECTION ELECTRONICS   DAHISAR EAST` and `SELECTION ELECTRONICS` would group
as two different vendors, which silently corrupts every "spend by vendor"
aggregate. Do not guess a fix from the ten sample rows — build a place list
from the real corpus.

**Owner: Stream 1.** Report parse coverage (`make enrich-report`) and put that
percentage in the deck. Honest coverage numbers are worth more than a claim of
perfection, and the assistant should say when a counterparty could not be
parsed rather than dropping the row from a total.

## 4. Negative account balances

`available_balance` runs to −131,629,423.33 on several accounts. Overdraft
facility? Sign convention? Bad export? **Ask the organisers.** If a judge asks
"why is this balance negative" and you don't know, that costs more than the
feature you'd have built instead.

## 5. Scope: which questions are we promising?

The problem statement explicitly allows a well-scoped subset. With this schema
the defensible scope is:

- spend / receipts by counterparty, channel, bank, account, entity, period
- transaction lookup by reference number
- reconciliation state under our stated definition
- period-over-period comparison

Everything else — budgets, forecasts, categories, chart of accounts, tax — is
**not in the data** and the assistant must say so. That refusal is a scored
requirement, not a gap.
