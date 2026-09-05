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

# defined after PROVIDER below via _resolve(); see DEFAULT_BASE_URL
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or "ollama"
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "90"))

PROVIDER = os.getenv("LLM_PROVIDER", CFG.get("provider", "ollama"))
# Ollama serves params baked into a derived model; a hosted API takes them per
# request, so there is nothing to derive and we call the base model directly.
MODEL_KEY = "ollama_base" if PROVIDER == "ollama" else "base"

DEFAULT_BASE_URL = {
    "ollama": "http://localhost:11434/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}.get(PROVIDER, "http://localhost:11434/v1")

BASE_URL = os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)

ROLES = CFG["roles"]
MODELS = {r: c[MODEL_KEY] for r, c in ROLES.items()}


def set_model(role: str, model: str) -> None:  # noqa: D401
    """Point one role at a different model for this process only.

    Used by the eval harness to run the same golden set across candidates --
    the model-choice bonus wants evidence, not an opinion. Never call this from
    request-handling code: the committed config is what makes the team's
    numbers comparable.
    """
    ROLES[role] = {**ROLES[role], MODEL_KEY: model}
    MODELS[role] = model


class ModelUnavailable(RuntimeError):
    """Raised loudly on purpose. A silent fallback to a different model would
    destroy the one property this whole setup exists to guarantee."""


USAGE: list[dict] = []   # append-only call log -> efficiency stats for the deck


def chat(role: str, system: str, user: str, *, temperature: float | None = None,
         json_mode: bool = False, max_tokens: int = 512) -> str:
    cfg = ROLES[role]
    model = cfg.get(MODEL_KEY, cfg["base"])
    # Qwen3 thinking models waste tokens on reasoning chains.
    # Prepend /no_think to the system prompt to disable it.
    if "qwen3" in model:
        system = "/no_think\n" + system
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        # committed defaults; only self-consistency sampling overrides them
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "top_p": cfg["top_p"],
        "max_tokens": max_tokens,
    }
    # `seed` is an Ollama/OpenAI parameter; Google's compatibility layer
    # rejects unknown fields, so only send it where it is supported.
    if PROVIDER in ("ollama", "hosted"):
        payload["seed"] = cfg["seed"]
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    try:
        r = httpx.post(f"{BASE_URL}/chat/completions", json=payload, timeout=TIMEOUT,
                       headers={"Authorization": f"Bearer {API_KEY}"})
    except httpx.ConnectError as e:
        raise ModelUnavailable(f"Cannot reach {BASE_URL}.") from e

    if r.status_code in (401, 403):
        raise ModelUnavailable(
            f"{BASE_URL} rejected the credentials. Set GEMINI_API_KEY in .env "
            f"(get one from https://aistudio.google.com/apikey)."
            if PROVIDER == "gemini" else
            f"{BASE_URL} rejected the credentials. Check LLM_API_KEY in .env.")
    if r.status_code == 429:
        raise ModelUnavailable(
            f"Rate limited by {BASE_URL}. Free tiers throttle quickly -- an eval "
            f"run is ~150 calls. Wait, or lower confidence.samples in "
            f"config/models.yaml.")

    if r.status_code == 404:
        raise ModelUnavailable(
            f"Model '{model}' is not available at {BASE_URL}."
            + (" The host must run `make model-build`." if PROVIDER == "ollama" else "")
        )
    r.raise_for_status()

    data = r.json()
    USAGE.append({"role": role, "model": model,
                  "tokens": data.get("usage", {}).get("total_tokens")})
    msg = data["choices"][0]["message"]
    # qwen3 "thinking" models return reasoning + content; content may be empty
    # if max_tokens was consumed by reasoning. Fall back to reasoning if needed.
    content = msg.get("content") or ""
    if not content.strip() and msg.get("reasoning"):
        content = msg["reasoning"]
    return content


def _extract_json(raw: str) -> dict:
    """Extract the first valid JSON object from a string that may contain
    prose, markdown fences, or multiple objects — all common with small models."""
    # Try the whole string first
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass
    # Strip markdown fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`")
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        pass
    # Walk character by character to find balanced braces
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"no JSON in model output: {raw[:200]}")
    depth, i = 0, start
    in_str = False
    while i < len(raw):
        c = raw[i]
        if c == '"' and (i == 0 or raw[i-1] != '\\'):
            in_str = not in_str
        elif not in_str:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(raw[start:i+1])
                    except json.JSONDecodeError:
                        # Try next opening brace
                        start = raw.find("{", i+1)
                        if start == -1:
                            break
                        depth, i = 0, start
                        continue
        i += 1
    raise ValueError(f"no valid JSON in model output: {raw[:200]}")


def chat_json(role: str, system: str, user: str, *, temperature: float | None = None) -> dict:
    """Small models wrap JSON in prose or fences more often than large ones.
    Salvage it rather than failing the query."""
    raw = chat(role, system, user, temperature=temperature, json_mode=True)
    return _extract_json(raw)


def efficiency_report() -> dict:
    """How often did we escalate? That number is worth 20% of the score."""
    total = len(USAGE)
    esc = sum(1 for u in USAGE if u["role"] == "escalate")
    return {"endpoint": BASE_URL, "calls": total, "escalations": esc,
            "escalation_rate": round(esc / total, 3) if total else 0.0,
            "by_model": {m: sum(1 for u in USAGE if u["model"] == m)
                         for m in {u["model"] for u in USAGE}}}
