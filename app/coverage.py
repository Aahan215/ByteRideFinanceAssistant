"""Concept coverage: does every substantive word in the question map to
something this system can actually express?

THE PROBLEM THIS SOLVES. Constrained decoding forces the model to emit a
VALID QuerySpec. When the question is about something the schema cannot
express -- a discount, a budget, a reconciliation status -- the model cannot say
"I can't", so it emits the nearest expressible query: top vendors, or total
spend. A different question, answered confidently.

A blocklist (app/planner.OUT_OF_SCOPE) catches what was anticipated. This is
the inverse: an ALLOWLIST of what the system knows how to talk about. Every
content word in the question must be accounted for by one of:

    the schema vocabulary   metrics, dimensions, datasets, categories, channels
    date language           handled deterministically by app/nlq_dates
    question grammar        how / much / which / show / my / ...
    a real vendor name      anything the validator can resolve

Whatever is left is a concept nobody can express. That is a refusal, and the
refusal can name the exact word -- which is far more useful than a generic
"I can't help with that".

Deterministic, testable without a model, and it runs AFTER the model so the
spec's own filter values count as coverage (the model naming a vendor covers
that vendor's words).
"""
from __future__ import annotations
import functools
import re

from app.db import SEMANTIC, run

# --- vocabulary the system can express ----------------------------------------
METRIC_WORDS = """
total totals sum count number numbers average avg mean largest biggest smallest
max maximum min minimum highest lowest most least top bottom first last
best worst cheapest priciest
""".split()

# Grouping verbs: "split across banks", "divide by category".
GROUPING_WORDS = """
split splits splitting divide divided dividing distribute distributed distribution
allocate allocated allocation share shared shares spread grouped group grouping
""".split()

DIMENSION_WORDS = """
vendor vendors merchant merchants payee payees counterparty counterparties supplier
suppliers shop shops store stores place places category categories channel channels
bank banks account accounts entity entities program programme month months monthly
quarter quarters quarterly year years yearly annual week weeks weekly day days daily
type types
""".split()

DATASET_WORDS = """
spend spends spent spending pay pays paid paying payment payments payout payouts
expense expenses outflow outgoing outbound receive received receiving receipt receipts
income incoming inbound credit credits credited debit debits debited transaction
transactions txn txns money amount amounts cash bought buy buying purchase purchases
purchased cost costs send sends sent sending transferred remit remitted wire wired
expenditure expenditures outlay outlays disbursement disbursements remittance
remittances spending outgo fork forked shell shelled dish dished splurge splurged
splash splashed frequent frequented visit visited visits patronise patronize
""".split()

DATE_WORDS = """
today yesterday tomorrow now current currently recent recently latest last previous
prior past this next ago since between from until till during within period periods
time date dates range earlier later ytd
january february march april may june july august september october november
december jan feb mar apr jun jul aug sep sept oct nov dec
""".split()

COMPARE_WORDS = """
compare compared comparison comparing versus vs against before after change changed
changes difference different trend trends trending over movement grow grew growth
increase increased decrease decreased up down more less fewer higher lower same
similar instead rather
""".split()

CHANNEL_WORDS = "upi imps neft rtgs ft cheque cheques chq online transfer transfers".split()

# Frequency and degree adverbs: "most often", "usually", "roughly".
ADVERBS = """
often frequently usually normally typically regularly rarely seldom always never
sometimes mostly mainly largely generally roughly approximately nearly almost
""".split()

# Question shapes handled deterministically elsewhere in the planner.
HANDLED_SHAPES = """
save saving savings cut cutting control controlling reduce reducing trim tighten
unusual anomaly anomalies outlier outliers suspicious odd weird strange
""".split()

# Question grammar and glue. Generous on purpose: a false refusal on "please"
# would be far more annoying than the failure this file exists to catch.
FUNCTION_WORDS = """
a an the and or but nor so yet if then than that those these this it its them
they their there here what which who whom whose where when why how much many
do does did done is are was were be been being have has had having can could
would should will shall may might must i me my mine we us our ours you your
yours he she his her him of on for in at to by with about into onto per each
every all any some none no not only just also too very really quite rather
show shows showing list lists listing give gives giving tell tells telling get
gets getting find finds finding see look looks looking check display fetch pull
provide provides providing supply supplies supplying share shares sharing
break breakdown broken down out up off over across through via using use used
made make makes making go goes went going come comes came coming want wants
wanted need needs needed like likes liked please thanks thank hey hi hello
ok okay yes yeah sure right well let lets lot lots bit little much more most
isn't aren't wasn't weren't hasn't haven't hadn't doesn't don't didn't can't
couldn't won't wouldn't shouldn't isnt arent wasnt hasnt havent doesnt dont didnt
whole entire overall everything anything something nothing where anywhere
someone anyone everyone all both either neither around roughly approximately
exactly about wise basis vs etc e.g i.e
""".split()

# Nouns that belong to the assistant itself rather than the data.
META_WORDS = """
answer answers question questions query queries result results data details
detail info information summary report breakdown chart table view figure figures
number numbers value values
""".split()


def _category_words() -> set[str]:
    from app.planner import CATEGORY_CUES
    words: set[str] = set()
    for pattern in CATEGORY_CUES.values():
        # pull plain words out of the regex alternations
        for w in re.findall(r"[a-z]{3,}", pattern.lower()):
            words.add(w)
    for cat in SEMANTIC.get("spend_categories", []):
        words.update(cat.lower().split("_"))
    return words


@functools.lru_cache(maxsize=1)
def vocabulary() -> frozenset[str]:
    words: set[str] = set()
    for group in (METRIC_WORDS, DIMENSION_WORDS, DATASET_WORDS, DATE_WORDS,
                  COMPARE_WORDS, CHANNEL_WORDS, HANDLED_SHAPES, ADVERBS,
                  GROUPING_WORDS, FUNCTION_WORDS, META_WORDS):
        words.update(group)
    words.update(_category_words())
    for dim in SEMANTIC["dimensions"]:
        words.update(dim.lower().split("_"))
    for ds in SEMANTIC["datasets"]:
        words.add(ds.lower())
    return frozenset(words)


@functools.lru_cache(maxsize=1)
def vendor_words() -> frozenset[str]:
    """Every word that appears in a known counterparty name, so "zomato" and
    "bajaj" are covered without the model having to name them."""
    try:
        rows = run(f"SELECT DISTINCT counterparty FROM {SEMANTIC['base_view']} "
                   f"WHERE counterparty IS NOT NULL")
        words: set[str] = set()
        for (name,) in rows.values:
            words.update(w.lower() for w in str(name).split() if len(w) > 2)
        return frozenset(words)
    except Exception:
        return frozenset()


@functools.lru_cache(maxsize=1)
def bank_words() -> frozenset[str]:
    """Every word of every bank name, plus every bank code, so "SBIN", "kotak"
    and "state bank" are covered. Vendor words were; bank words were not, and
    "SBIN" was refused as a concept nobody could express."""
    try:
        rows = run("SELECT bank_code, bank_name FROM bank")
        words: set[str] = set()
        for code, name in rows.values:
            words.add(str(code).lower())
            words.update(w.lower() for w in str(name).split() if len(w) > 2)
        return frozenset(words)
    except Exception:
        return frozenset()


_TOKEN = re.compile(r"[a-z][a-z'-]+")


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + (ca != cb))
        prev = curr
    return prev[-1]


def _fuzzy_covered(word: str, vocab: frozenset[str]) -> bool:
    """Typo tolerance: a misspelling like "trasaansaction" or "insuarance"
    should still resolve to "transaction"/"insurance" rather than refuse the
    whole question. Edit distance 1 for short words, 2 for longer ones --
    tight enough that two different real words rarely collide, tried only
    against the fixed vocabulary (not vendor/bank names, which are proper
    nouns and far more numerous, so fuzzy-matching there risks false hits).
    """
    max_dist = min(3, max(1, round(len(word) * 0.2)))
    for cand in vocab:
        if abs(len(cand) - len(word)) > max_dist:
            continue
        if _levenshtein(word, cand) <= max_dist:
            return True
    return False


def _stem(word: str) -> set[str]:
    """Cheap inflection folding so "vendors" matches "vendor" and "paying"
    matches "pay". Not a stemmer; just the endings that matter here."""
    forms = {word}
    for suffix in ("s", "es", "ed", "ing", "ly", "er", "est", "'s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            forms.add(word[: -len(suffix)])
    if word.endswith("ies") and len(word) > 4:
        forms.add(word[:-3] + "y")
    return forms


def unresolved(question: str, spec_terms: list[str] | None = None) -> list[str]:
    """Content words in the question that nothing can account for.

    `spec_terms` are the filter values the model actually produced (a vendor
    name, say), which count as coverage: if the model named it, it was heard.
    """
    vocab = vocabulary()
    vendors = vendor_words()
    spec_words: set[str] = set()
    for term in spec_terms or []:
        spec_words.update(w.lower() for w in re.findall(r"[a-z]+", str(term).lower()))

    out: list[str] = []
    for tok in _TOKEN.findall(question.lower()):
        tok = tok.strip("'-")
        if len(tok) < 4:
            continue                                   # too short to be a concept
        forms = _stem(tok)
        if forms & vocab or forms & vendors or forms & bank_words() or forms & spec_words:
            continue
        if _fuzzy_covered(tok, vocab):
            continue
        if tok not in out:
            out.append(tok)
    return out
