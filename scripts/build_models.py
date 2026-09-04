"""HOST ONLY. Bakes config/models.yaml into named Ollama models.

Why derive models instead of sending params per request: the OpenAI-compatible
endpoint does not accept `num_ctx`, so context size would fall back to whatever
the host's default is. Baking params into the model means the server enforces
them, and a client that forgets to send temperature still gets the right one.
"""
import pathlib, subprocess, sys, tempfile
import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())


def sh(*args, **kw):
    return subprocess.run(args, check=True, text=True, **kw)


def have(model: str) -> bool:
    out = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
    return any(line.split()[0] == model for line in out.splitlines()[1:] if line.strip())


for role, c in CFG["roles"].items():
    base, derived = c["base"], c["derived"]
    print(f"\n=== {role}: {base} -> {derived} ===")

    if not have(base):
        try:
            sh("ollama", "pull", base)
        except subprocess.CalledProcessError:
            print(f"!! could not pull {base}. Edit config/models.yaml and pick "
                  f"a smaller base for '{role}', then re-run.")
            continue

    modelfile = "\n".join([
        f"FROM {base}",
        f"PARAMETER temperature {c['temperature']}",
        f"PARAMETER top_p {c['top_p']}",
        f"PARAMETER seed {c['seed']}",
        f"PARAMETER num_ctx {c['num_ctx']}",
    ])
    with tempfile.NamedTemporaryFile("w", suffix=".Modelfile", delete=False) as f:
        f.write(modelfile + "\n")
        path = f.name
    sh("ollama", "create", derived, "-f", path)
    print(f"  created {derived}")

print("\nNow share the endpoint with the team:")
ip = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True).stdout.strip()
print(f"  LLM_BASE_URL=http://{ip or '<your-ip>'}:11434/v1")
print("\nIf the venue wifi isolates clients, use a tunnel instead:")
print("  ollama serve  &&  cloudflared tunnel --url http://localhost:11434")
