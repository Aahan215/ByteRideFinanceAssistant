# Open decisions — resolve these in the first hour

The real schema (`schema/DATA_DICTIONARY.md`) does not contain several things
the questions need. These are **judgement calls, not lookups.** Each needs an
owner, a decision, and a line in the deck — judges will ask.

---

## 1. ~~Reconciliation~~ — DROPPED

Out of scope: the data does not support it. The assistant must **say so** when
asked rather than inventing a status. See #5.

## 2. Scope: personal spend analytics

The assistant answers questions about one entity's spending:

- where did I spend the most this month / this quarter
- total tax paid in the last N months
- spend by counterparty, category, channel, bank, period
- period-over-period comparison
- transaction lookup by reference number

Everything else — budgets, forecasts, reconciliation, chart of accounts — is
**not in the data** and must be refused. That refusal is a scored requirement.

## 3. Categories are derived, not stored

There is no category column. `app/enrich.py` classifies each narration at load
time into TAX, BANK_CHARGES, INTEREST, EMI_LOAN, SALARY, UTILITIES, INSURANCE,
INVESTMENT, CASH, CHEQUE, RENT, TRANSFER, UNCATEGORISED.

**Owner: Stream 1.** The keyword rules are tuned against a handful of examples,
not the real corpus. Two things to do when the export lands:

- Report the **UNCATEGORISED percentage** and put it in the deck. If it is high,
  the "where did I spend the most" answer is misleading.
- Sanity-check TAX specifically, since a whole question depends on it. Indian
  narrations spell it many ways (GST, CGST, TDS, CHALLAN, self-assessment).

Unmatched narrations become UNCATEGORISED on purpose — never forced into a
bucket, so the assistant can disclose the gap instead of hiding it.

## 4. Vendors live inside free text

No vendor table. Counterparty is parsed from the narration at load time.

**Open sub-problem:** trailing branch/location noise. `SELECTION ELECTRONICS
DAHISAR EAST` and `SELECTION ELECTRONICS` currently group as two vendors, which
silently corrupts every "where did I spend most" answer. Build a place list from
the real corpus — do not guess from ten sample rows.

## 5. Encryption: decrypt in the ETL, never in a query

`account_id`, `entity_id` and other personal fields arrive AES-256 encrypted.

**Run `python scripts/crypto_probe.py` on the real export before writing any
crypto-dependent code.** It reports cipher mode, whether the encryption is
deterministic, and whether cross-table ciphertext joins work.

What the sample already tells us:

- `utr_number` ciphertexts are 42/44/48 bytes — **not** multiples of 16, so a
  stream mode (CTR/CFB/GCM), not padded CBC/ECB.
- Every ciphertext shares a 16-byte prefix, and pairs share 27–28 → **fixed
  nonce, keystream reuse.** Deterministic, therefore joinable on ciphertext.

**Decisions that follow:**

1. **Do not decrypt at query time.** 20M rows × per-value Python AES is tens of
   seconds per question. All crypto belongs in `scripts/load_data.py`.
2. **Prefer tokenising to decrypting.** Deterministic encryption means
   `transaction.account_id` joins to `account.account_id` on ciphertext with no
   key at all. Where a short key is wanted, `crypto.surrogate()` hashes the
   ciphertext to an opaque `ACC_xxxxxxxxxx`. Joins and group-bys work and **no
   plaintext PII lands in DuckDB, in a prompt, or on screen.**
3. **Decrypt only content that drives analysis.** If `description` becomes
   encrypted, decrypt it in the ETL to parse counterparty and category, then
   keep only the derived columns.
4. **`account_number` and `utr_number` stay masked** — masking happens in SQL,
   so raw values never leave the database.
5. **The key lives in `.env`, never in git.** `FINANCE_AES_KEY`,
   `FINANCE_AES_IV`, `FINANCE_AES_MODE`.

**For the deck:** note that the sample uses a fixed nonce, and that production
would want per-row nonces plus a separate deterministic (SIV) column for joins.
Knowing the trade-off is worth more than silently copying it.

## 6. Query engine: DuckDB. Snowflake not used. — DECIDED

Their analytics run on Snowflake, and we considered matching it. Decided
against for this build:

- The visible demo difference is nil. The chat, the answer and the breakdown
  are identical; only the latency is worse (~30ms local vs a few hundred ms
  over the network).
- It puts the demo on the venue wifi. A dropped network means no demo at all.
- A suspended warehouse takes seconds to auto-resume, which lands as a silent
  pause at the worst possible moment.

**What we say if asked:** the compiler emits portable SQL against a single view,
so the engine is an adapter, not a rewrite. `date_trunc`, `ILIKE`, `right()` and
`?` binding all work on both. The one real porting task is Snowflake
upper-casing unquoted identifiers, which changes result-dict keys and would
break the UI and the numeric guard. Loading differs too: no `read_csv_auto`, so
`PUT` + `COPY INTO` or `write_pandas`.

Knowing exactly what porting would cost is a better answer than having half-built
it.

## 7. Negative account balances

`available_balance` runs to −131,629,423.33 on several accounts. Overdraft?
Sign convention? Bad export? **Ask the organisers.**
