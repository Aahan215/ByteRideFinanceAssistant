"""Load .env before anything reads os.environ.

Every entry point (API, eval harness, scripts) imports from `app`, so putting
the load here means nobody has to remember to source the file -- and a missing
key surfaces as a clear ModelUnavailable rather than a silent fallback to
whatever was already in the shell.
"""
import pathlib

try:
    from dotenv import load_dotenv
    load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env", override=False)
except ModuleNotFoundError:      # dotenv is optional; env vars still work
    pass
