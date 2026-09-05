"""Model provider shim.

Design rule: `.env` says WHICH MACHINE. `config/models.yaml` says HOW THE MODEL
BEHAVES, and it is committed. A teammate cannot silently drift onto a different
model or different sampling params, because those live in git and are baked
into the derived models on the host.
"""
from __future__ import annotations
import json, os, pathlib, re, time
import httpx, yaml

from app import boundary

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())

# defined after PROVIDER below via _resolve(); see DEFAULT_BASE_URL
API_KEY = os.getenv("LLM_API_KEY") or os.getenv("GEMINI_API_KEY") or "ollama"
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "90"))

PROVIDER = os.getenv("LLM_PROVIDER", CFG.get("provider", "ollama"))
# Ollama serves params baked into a derived model; a hosted API takes them per
# request, so there is nothing to derive and we call the base model directly.
# Was "derived" (a Modelfile with params baked in) because the OpenAI-compat
# endpoint could not pass num_ctx. The native path passes every option per
# request, so the extra build step is gone -- one less thing to run on a fresh
# clone, and one less way for the team's configs to diverge.
MODEL_KEY = "ollama_base" if PROVIDER == "ollama" else "base"

DEFAULT_BASE_URL = {
    "ollama": "http://localhost:11434/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}.get(PROVIDER, "http://localhost:11434/v1")

BASE_URL = os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL)
# Native Ollama root, derived from the compat URL by stripping the /v1 suffix.
OLLAMA_NATIVE = re.sub(r"/v1/?$", "", BASE_URL)

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


# Reasoning models (qwen3, gemini) burn completion tokens on thoughts before
# emitting content, and a budget that looks generous returns empty content with
# finish_reason "length". qwen3:4b spent 191 tokens deciding that the capital of
# France is Paris. Costs nothing on non-reasoning models -- they stop early.
DEFAULT_MAX_TOKENS = 1500


# Ollama's OpenAI-compatible endpoint silently IGNORES response_format, so a
# reasoning model rambles to the token limit and returns nothing: 46.8s and
# 1500 wasted tokens. Its native /api/chat honours `format`, which constrains
# decoding to JSON and produced the identical answer in 1.4s from 42 tokens.
# A 33x difference, so the ollama path does not go through the compat layer.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")


def _chat_ollama(role: str, cfg: dict, model: str, system: str, user: str,
                 temperature: float, json_mode: bool, max_tokens: int,
                 schema: dict | None = None) -> str:
    body = {
        "model": model,
        "stream": False,
        # Reasoning is not worth 40 seconds for a schema-constrained JSON object.
        "think": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,   # avoid a 2.5GB reload between turns
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "options": {
            "temperature": temperature,
            "top_p": cfg["top_p"],
            "seed": cfg["seed"],
            # num_ctx is settable here; the compat endpoint has no way to pass it
            "num_ctx": cfg["num_ctx"],
            "num_predict": max_tokens,
        },
    }
    if schema is not None:
        # A schema is strictly better than format="json": plain JSON mode let
        # qwen3:4b emit a valid object and then pad with whitespace until it hit
        # the token limit, truncating before the closing brace.
        body["format"] = schema
    elif json_mode:
        body["format"] = "json"
    try:
        r = httpx.post(f"{OLLAMA_NATIVE}/api/chat", json=body, timeout=TIMEOUT)
    except httpx.ConnectError as e:
        raise ModelUnavailable(f"Cannot reach Ollama at {OLLAMA_NATIVE}.") from e
    if r.status_code == 404:
        raise ModelUnavailable(f"Model '{model}' is not pulled. Run `ollama pull {model}`.")
    r.raise_for_status()
    data = r.json()
    USAGE.append({"role": role, "model": model, "tokens": data.get("eval_count")})
    content = (data.get("message") or {}).get("content")
    if not content:
        raise ModelUnavailable(
            f"{model} returned no content. Reasoning tokens can consume the whole "
            f"num_predict budget; raise max_tokens or keep json_mode on.")
    return content


def chat(role: str, system: str, user: str, *, temperature: float | None = None,
         json_mode: bool = False, max_tokens: int = DEFAULT_MAX_TOKENS,
         schema: dict | None = None) -> str:
    cfg = ROLES[role]
    model = cfg.get(MODEL_KEY, cfg["base"])
    temp = cfg["temperature"] if temperature is None else temperature

    boundary.record(role, model, system + "\n" + user)
    if PROVIDER == "ollama":
        return _chat_ollama(role, cfg, model, system, user, temp,
                            json_mode or schema is not None, max_tokens, schema)

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        # committed defaults; only self-consistency sampling overrides them
        "temperature": temp,
        "top_p": cfg["top_p"],
        "max_tokens": max_tokens,
    }
    # `seed` is an Ollama/OpenAI parameter; Google's compatibility layer
    # rejects unknown fields, so only send it where it is supported.
    if PROVIDER in ("ollama", "hosted"):
        payload["seed"] = cfg["seed"]
    if json_mode or schema is not None:
        payload["response_format"] = {"type": "json_object"}

    # Single choke point: nothing reaches a model without passing the boundary
    # check and being written to the audit trail.
    boundary.record(role, model, system + "\n" + user)

    # Free tiers throttle hard and a full eval run is well over a hundred calls.
    # Back off and retry rather than scoring a rate limit as a wrong answer.
    for attempt in range(4):
        try:
            r = httpx.post(f"{BASE_URL}/chat/completions", json=payload, timeout=TIMEOUT,
                           headers={"Authorization": f"Bearer {API_KEY}"})
        except httpx.ConnectError as e:
            raise ModelUnavailable(f"Cannot reach {BASE_URL}.") from e
        if r.status_code != 429 or attempt == 3:
            break
        retry_after = r.headers.get("retry-after")
        time.sleep(float(retry_after) if retry_after else 2 ** attempt * 4)

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

    choice = (data.get("choices") or [{}])[0]
    content = (choice.get("message") or {}).get("content")
    if not content:
        raise ModelUnavailable(
            f"{model} returned no content (finish_reason="
            f"{choice.get('finish_reason')!r}). Raise max_tokens: reasoning "
            f"tokens count against the budget.")
    return content


def chat_json(role: str, system: str, user: str, *, temperature: float | None = None,
              schema: dict | None = None) -> dict:
    """Small models wrap JSON in prose or fences, and truncate. Salvage it."""
    raw = chat(role, system, user, temperature=temperature, json_mode=True, schema=schema)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # Truncated mid-object: the content is valid up to the cut, so close the
    # open brackets and take what we have rather than discarding the whole turn.
    start = raw.find("{")
    if start >= 0:
        frag = raw[start:].rstrip().rstrip(",")
        stack = []
        in_str = esc = False
        for ch in frag:
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
            elif ch == '"': in_str = True
            elif ch in "{[": stack.append("}" if ch == "{" else "]")
            elif ch in "}]" and stack: stack.pop()
        if in_str:
            frag += '"'
        try:
            return json.loads(frag + "".join(reversed(stack)))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"no usable JSON in model output: {raw[:200]}")


def efficiency_report() -> dict:
    """How often did we escalate? That number is worth 20% of the score."""
    total = len(USAGE)
    esc = sum(1 for u in USAGE if u["role"] == "escalate")
    return {"endpoint": BASE_URL, "calls": total, "escalations": esc,
            "escalation_rate": round(esc / total, 3) if total else 0.0,
            "by_model": {m: sum(1 for u in USAGE if u["model"] == m)
                         for m in {u["model"] for u in USAGE}}}
