"""Who the assistant is answering for.

There is no auth system -- the brief puts that out of scope -- but "my spending"
still needs an owner, and one user must not see another's transactions. This is
a selector, not a security boundary: it constrains what the assistant queries,
it does not authenticate anyone.

Three levels:
    all       every account (the analyst / admin view)
    entity    one customer, which may own several accounts
    account   a single bank account

DESIGN RULE: scope is NEVER part of QuerySpec and never appears in a prompt.
The model cannot see it, set it, or widen it -- it is applied by the compiler
after the model has finished. A model that could choose its own scope would
make the whole thing decorative.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

from app.db import SEMANTIC, run

Level = Literal["all", "entity", "account"]

COLUMN: dict[str, str] = {"entity": "entity_id", "account": "account_id"}


@dataclass(frozen=True)
class Scope:
    level: Level = "all"
    value: str | None = None

    def predicate(self) -> tuple[str | None, list]:
        """The WHERE fragment every query gets. `all` adds nothing."""
        if self.level == "all" or not self.value:
            return None, []
        col = COLUMN[self.level]
        return f"{col} = ?", [self.value]

    def label(self) -> str:
        return "All accounts" if self.level == "all" else f"{self.level}: {self.value[:12]}…"


ALL = Scope()


def parse(level: str | None, value: str | None) -> Scope:
    """Reject anything not recognised rather than silently widening to `all`.

    Falling back to `all` on a typo would quietly show one user everyone else's
    data -- the exact failure this exists to prevent.
    """
    if not level or level == "all":
        return ALL
    if level not in COLUMN:
        raise ValueError(f"unknown scope level {level!r}; expected all, entity or account")
    if not value:
        raise ValueError(f"scope level {level!r} needs a value")
    return Scope(level, value)  # type: ignore[arg-type]


def available() -> dict:
    """What the selector offers.

    Labels avoid raw identifiers: an account shows its bank and the last-4 mask
    already stored by the loader, and an entity is numbered by account count.
    """
    view = SEMANTIC["base_view"]
    accounts = run(f"""
        SELECT account_id, any_value(bank_name) AS bank,
               any_value(account_number) AS masked, COUNT(*) AS txns
        FROM {view} WHERE account_id IS NOT NULL
        GROUP BY account_id ORDER BY txns DESC""")
    entities = run(f"""
        SELECT entity_id, COUNT(DISTINCT account_id) AS accounts, COUNT(*) AS txns
        FROM {view} WHERE entity_id IS NOT NULL
        GROUP BY entity_id ORDER BY txns DESC""")

    return {
        "all": {"level": "all", "label": "All accounts",
                "txns": int(accounts["txns"].sum()) if len(accounts) else 0},
        "entities": [
            {"level": "entity", "value": r.entity_id,
             "label": f"Entity {i + 1} ({r.accounts} account{'s' if r.accounts != 1 else ''})",
             "accounts": int(r.accounts), "txns": int(r.txns)}
            for i, r in enumerate(entities.itertuples())
        ],
        "accounts": [
            {"level": "account", "value": r.account_id,
             "label": f"{r.bank or 'Unknown bank'} — {r.masked or 'account'}",
             "txns": int(r.txns)}
            for r in accounts.itertuples()
        ],
    }
