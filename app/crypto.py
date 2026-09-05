"""AES-256 handling for encrypted columns.

THE RULE: decryption happens ONCE, at load time, never inside a query.

At 20M rows, decrypting per query in Python costs tens of seconds per question.
The assistant must answer in about a second, so all crypto work belongs in the
ETL -- exactly like counterparty parsing.

THE BETTER RULE: for join keys, do not decrypt at all. If the encryption is
deterministic (same plaintext -> same ciphertext, which the sample data
indicates), ciphertext is a perfectly good join key and a perfectly good group
key. Map each distinct ciphertext to a short surrogate and no plaintext PII
ever touches the analytical store.

Run scripts/crypto_probe.py against the real export before relying on any of
this -- it reports whether the encryption is actually deterministic.
"""
from __future__ import annotations
import base64, functools, hashlib, os
from typing import Iterable

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

# Key never lives in git. Host exports it; .env.example documents the name.
KEY_ENV = "FINANCE_AES_KEY"      # base64 or hex, 32 bytes for AES-256
IV_ENV = "FINANCE_AES_IV"        # only for fixed-IV/nonce schemes
MODE = os.getenv("FINANCE_AES_MODE", "ctr").lower()   # ctr | cbc | gcm


class CryptoNotConfigured(RuntimeError):
    """Raised loudly. Silently returning ciphertext as if it were plaintext
    would put base64 blobs into answers and nobody would notice until the demo."""


def _decode_key(raw: str) -> bytes:
    for dec in (bytes.fromhex, base64.b64decode):
        try:
            k = dec(raw)
            if len(k) in (16, 24, 32):
                return k
        except Exception:
            continue
    raise CryptoNotConfigured(f"{KEY_ENV} is not a valid 16/24/32-byte hex or base64 key")


@functools.lru_cache(maxsize=1)
def _key() -> bytes:
    raw = os.getenv(KEY_ENV)
    if not raw:
        raise CryptoNotConfigured(
            f"{KEY_ENV} is not set. The organisers' key goes in .env (never in git).")
    return _decode_key(raw)


@functools.lru_cache(maxsize=1)
def _iv() -> bytes:
    raw = os.getenv(IV_ENV)
    return _decode_key(raw) if raw else b"\x00" * 16


def decrypt(value: str | None, *, iv_prefixed: bool = True) -> str | None:
    """Decrypt one base64 ciphertext. Use in the ETL, or for a single-row
    drill-down. Never map this over a whole column at query time."""
    if value is None or value == "":
        return None
    blob = base64.b64decode(value + "=" * (-len(value) % 4))

    if iv_prefixed and len(blob) > 16:
        iv, body = blob[:16], blob[16:]
    else:
        iv, body = _iv(), blob

    if MODE == "ctr":
        c = Cipher(algorithms.AES(_key()), modes.CTR(iv))
        return c.decryptor().update(body).decode("utf-8", "replace")
    if MODE == "gcm":
        tag, body = body[-16:], body[:-16]
        c = Cipher(algorithms.AES(_key()), modes.GCM(iv, tag))
        return c.decryptor().update(body).decode("utf-8", "replace")
    if MODE == "cbc":
        c = Cipher(algorithms.AES(_key()), modes.CBC(iv))
        out = c.decryptor().update(body)
        return padding.PKCS7(128).unpadder().update(out).decode("utf-8", "replace")
    raise CryptoNotConfigured(f"unsupported FINANCE_AES_MODE={MODE!r}")


def surrogate(ciphertext: str | None, prefix: str = "ACC") -> str | None:
    """A stable, non-reversible stand-in for a join key.

    Deterministic encryption means we can key on ciphertext -- but ciphertext is
    long and still sensitive. Hash it to a short opaque id instead. Joins and
    group-bys work; nothing sensitive lands in DuckDB, in a prompt, or on screen.
    """
    if not ciphertext:
        return None
    h = hashlib.sha256(ciphertext.encode()).hexdigest()[:10]
    return f"{prefix}_{h}"


def is_deterministic(samples: Iterable[str]) -> bool:
    """Cheap check: re-encryption is not available to us, so instead we look for
    repeated ciphertexts where repeated plaintexts are expected. Used by the
    probe script; see there for the fuller diagnosis."""
    vals = [s for s in samples if s]
    return len(vals) != len(set(vals))
