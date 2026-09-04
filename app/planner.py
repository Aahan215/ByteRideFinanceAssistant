"""Natural language -> QuerySpec. The ONLY place an LLM sees the user's words.

Owner note: keep this file behind the QuerySpec contract. Swapping Qwen3-8B for
gpt-oss-20b, or a local model for a hosted one, must not change any other file.
"""
from __future__ import annotations
import json
from app.spec import QuerySpec

SPEC_SCHEMA_HINT = json.dumps(QuerySpec.model_json_schema(), indent=None)[:4000]

SYSTEM = f"""You translate finance questions into a QuerySpec JSON object.
You NEVER compute numbers. You NEVER invent vendor or category names.
If the question cannot be answered with this schema, set unsupported_reason.
Reply with JSON only, matching this schema:
{SPEC_SCHEMA_HINT}"""


def plan(question: str, prior: QuerySpec | None = None) -> QuerySpec:
    """TODO(owner: planner): call the local model, parse JSON, retry on invalid.
    For multi-turn, ask for a PATCH when `prior` is set and use prior.merge_patch().
    Self-consistency: sample 3x at temp 0.7; agreement -> high confidence."""
    raise NotImplementedError("planner not wired yet -- deterministic core works without it")
