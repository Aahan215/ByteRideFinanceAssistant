"""Model provider shim.

Only one machine on this team can host a local model, but everyone needs to
develop against one. This module makes the backend an env var, so:

  * the host Mac runs Ollama and shares it on the LAN
  * teammates point LLM_BASE_URL at that Mac
  * anyone offline falls back to the hackathon API credits
  * nobody's code changes when the model changes

Every call goes through here. No other file imports httpx or names a model.
"""
from __future__ import annotations
import json, os, re
import httpx

BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
API_KEY = os.getenv("LLM_API_KEY", "ollama")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))

# The cascade. Smallest model that does the job wins points here -- this dict
# is the artefact your model-efficiency slide is built from.
MODELS = {
    "router":   os.getenv("LLM_ROUTER",   "qwen3:0.6b"),   # is this a data question?
    "planner":  os.getenv("LLM_PLANNER",  "qwen3:8b"),     # text -> QuerySpec
    "narrator": os.getenv("LLM_NARRATOR", "qwen3:8b"),     # table -> prose
    "escalate": os.getenv("LLM_ESCALATE", "gpt-oss:20b"),  # only on low confidence
}

USAGE: list[dict] = []   # append-only call log -> efficiency stats for the deck


def chat(role: str, system: str, user: str, *, temperature: float = 0.0,
         json_mode: bool = False, max_tokens: int = 800) -> str:
    model = MODELS[role]
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    r = httpx.post(f"{BASE_URL}/chat/completions", json=payload, timeout=TIMEOUT,
                   headers={"Authorization": f"Bearer {API_KEY}"})
    r.raise_for_status()
    data = r.json()
    USAGE.append({"role": role, "model": model,
                  "tokens": data.get("usage", {}).get("total_tokens")})
    return data["choices"][0]["message"]["content"]


def chat_json(role: str, system: str, user: str, *, temperature: float = 0.0) -> dict:
    """Small models wrap JSON in prose or fences more often than big ones.
    Salvage it rather than failing the query."""
    raw = chat(role, system, user, temperature=temperature, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError(f"no JSON in model output: {raw[:200]}")
        return json.loads(m.group(0))


def efficiency_report() -> dict:
    """How often did we escalate? That number is worth 20% of the score."""
    total = len(USAGE)
    esc = sum(1 for u in USAGE if u["role"] == "escalate")
    return {"calls": total, "escalations": esc,
            "escalation_rate": round(esc / total, 3) if total else 0.0,
            "by_model": {m: sum(1 for u in USAGE if u["model"] == m)
                         for m in {u["model"] for u in USAGE}}}
