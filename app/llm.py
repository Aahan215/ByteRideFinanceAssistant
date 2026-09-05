"""Model provider shim.

Design rule: `.env` says WHICH MACHINE. `config/models.yaml` says HOW THE MODEL
BEHAVES, and it is committed. A teammate cannot silently drift onto a different
model or different sampling params, because those live in git and are baked
into the derived models on the host.
"""
from __future__ import annotations
import json, os, pathlib, re
import httpx, yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())

BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
API_KEY = os.getenv("LLM_API_KEY", "ollama")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "90"))

ROLES = CFG["roles"]
MODELS = {r: c["derived"] for r, c in ROLES.items()}


def set_model(role: str, model: str) -> None:
    """Point one role at a different model for this process only.

    Used by the eval harness to run the same golden set across candidates --
    the model-choice bonus wants evidence, not an opinion. Never call this from
    request-handling code: the committed config is what makes the team's
    numbers comparable.
    """
    ROLES[role] = {**ROLES[role], "derived": model}
    MODELS[role] = model


class ModelUnavailable(RuntimeError):
    """Raised loudly on purpose. A silent fallback to a different model would
    destroy the one property this whole setup exists to guarantee."""


USAGE: list[dict] = []   # append-only call log -> efficiency stats for the deck


def chat(role: str, system: str, user: str, *, temperature: float | None = None,
         json_mode: bool = False, max_tokens: int = 800) -> str:
    cfg = ROLES[role]
    payload = {
        "model": cfg["derived"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        # committed defaults; only self-consistency sampling overrides them
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "top_p": cfg["top_p"],
        "seed": cfg["seed"],
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        r = httpx.post(f"{BASE_URL}/chat/completions", json=payload, timeout=TIMEOUT,
                       headers={"Authorization": f"Bearer {API_KEY}"})
    except httpx.ConnectError as e:
        raise ModelUnavailable(
            f"Cannot reach the shared model server at {BASE_URL}.\n"
            f"Check the host machine is awake, then run `make model-check`.\n"
            f"Do NOT start your own Ollama -- results stop being comparable."
        ) from e

    if r.status_code == 404:
        raise ModelUnavailable(
            f"Model '{cfg['derived']}' is missing on the host. "
            f"The host must run `make model-build`."
        )
    r.raise_for_status()

    data = r.json()
    USAGE.append({"role": role, "model": cfg["derived"],
                  "tokens": data.get("usage", {}).get("total_tokens")})
    return data["choices"][0]["message"]["content"]


def chat_json(role: str, system: str, user: str, *, temperature: float | None = None) -> dict:
    """Small models wrap JSON in prose or fences more often than large ones.
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
    return {"endpoint": BASE_URL, "calls": total, "escalations": esc,
            "escalation_rate": round(esc / total, 3) if total else 0.0,
            "by_model": {m: sum(1 for u in USAGE if u["model"] == m)
                         for m in {u["model"] for u in USAGE}}}
