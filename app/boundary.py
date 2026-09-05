"""The data/model boundary — enforced and auditable.

The rule: the language model NEVER sees a row of data, and never touches the
database. It reads the user's question plus a description of the schema, and
emits a QuerySpec. Everything after that is deterministic Python and SQL.

    question ──► [ LLM ]──► QuerySpec ──► validator ──► compiler ──► DuckDB
                    ▲                                                  │
                    └──────────── never crosses back ──────────────────┘

That matters more now the model is a third-party API: anything in a prompt has
left the building. So every outbound call funnels through `record()`, which
keeps an audit trail you can actually show, and `assert_no_data()`, which fails
loudly if a payload contains something that looks like a database row.

`/boundary` exposes the trail.
"""
from __future__ import annotations
import os
import re
import time
from dataclasses import dataclass, field

# Set NARRATOR_MODE=model to let the model phrase the answer from the result
# table. That sends aggregate numbers to the provider, so it is OFF by default:
# the deterministic templates are never wrong and nothing leaves.
NARRATOR_MODE = os.getenv("NARRATOR_MODE", "template")

MAX_TRAIL = 200


@dataclass
class Crossing:
    at: float
    role: str
    model: str
    chars: int
    preview: str
    kind: str = "outbound"


TRAIL: list[Crossing] = field(default_factory=list)  # type: ignore[assignment]
TRAIL = []


class BoundaryViolation(RuntimeError):
    """A payload heading for the model contained something row-shaped."""


# Signatures of things that must never appear in a prompt. Deliberately narrow:
# broad heuristics would fire on ordinary schema text and get switched off.
_ROW_SIGNATURES = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I),
     "a transaction/account UUID"),
    (re.compile(r"\bXXXXXX\d{4}\b"), "a masked account number"),
    (re.compile(r"\[redacted\]"), "a redacted UTR"),
]


def assert_no_data(text: str, *, role: str) -> None:
    """Fail loudly rather than quietly leaking a row into a prompt."""
    for rx, what in _ROW_SIGNATURES:
        if rx.search(text):
            raise BoundaryViolation(
                f"Refusing to send {what} to the model (role={role}). "
                f"The model must only ever receive the question and the schema."
            )


def record(role: str, model: str, payload: str) -> None:
    assert_no_data(payload, role=role)
    TRAIL.append(Crossing(time.time(), role, model, len(payload),
                          payload[-180:].replace("\n", " ")))
    del TRAIL[:-MAX_TRAIL]


def report() -> dict:
    """What has actually crossed to the model this session."""
    return {
        "rule": "the model receives the question and the schema; never a data row",
        "narrator_mode": NARRATOR_MODE,
        "narrator_sends_results_to_model": NARRATOR_MODE == "model",
        "crossings": len(TRAIL),
        "by_role": {r: sum(1 for c in TRAIL if c.role == r) for r in {c.role for c in TRAIL}},
        "chars_sent": sum(c.chars for c in TRAIL),
        "recent": [{"role": c.role, "model": c.model, "chars": c.chars,
                    "preview": c.preview} for c in TRAIL[-10:]],
    }
