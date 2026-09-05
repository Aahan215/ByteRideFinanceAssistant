"""Everyone runs this. Proves you are on the shared server with the right models.

The canary is the real test: a fixed prompt whose output hash is committed. If
your hash differs from the lockfile, you are not talking to the same model the
golden-set numbers were produced on, and your accuracy figures are not
comparable to anyone else's.
"""
import hashlib, json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.llm import ROLES, BASE_URL, PROVIDER, MODELS, chat, ModelUnavailable

ROOT = pathlib.Path(__file__).resolve().parent.parent
LOCK = ROOT / "config" / "canary.lock"

CANARY_SYSTEM = "Reply with exactly one word, lowercase, no punctuation."
CANARY_USER = "What is the capital city of France?"


def fingerprint(role: str) -> str:
    # Generous budget on purpose: reasoning models spend tokens on thoughts
    # before emitting content, so a tight cap returns nothing and looks like
    # the model is broken.
    out = chat(role, CANARY_SYSTEM, CANARY_USER, temperature=0, max_tokens=256)
    return hashlib.sha256(out.strip().lower().encode()).hexdigest()[:16]


def main():
    write = "--write" in sys.argv
    print(f"provider: {PROVIDER}\nendpoint: {BASE_URL}")
    for role, model in MODELS.items():
        print(f"  {role:9} -> {model}")
    print()
    if PROVIDER == "ollama" and not write and \
            BASE_URL.startswith(("http://localhost", "http://127.0.0.1")):
        print("!! You are pointing at localhost. Unless you are the host, set "
              "LLM_BASE_URL in .env to the shared server.\n")

    lock = json.loads(LOCK.read_text()) if LOCK.exists() else {}
    results, drift = {}, False

    for role in ROLES:
        try:
            fp = fingerprint(role)
        except ModelUnavailable as e:
            print(f"  {role:9} UNAVAILABLE\n     {e}"); drift = True; continue
        results[role] = fp
        if role in lock and lock[role] != fp:
            print(f"  {role:9} DRIFT  expected {lock[role]}, got {fp}"); drift = True
        else:
            print(f"  {role:9} ok     {fp}")

    if write:
        LOCK.write_text(json.dumps(results, indent=2) + "\n")
        print(f"\nwrote {LOCK.name} -- commit it so the team can verify against it")
        return

    if drift:
        print("\nFAIL: your model behaviour differs from the committed lockfile.")
        sys.exit(1)
    print("\nOK: identical to the committed reference.")


if __name__ == "__main__":
    main()
