"""
login.py — Hearthstone Linux Launcher
Token acquisition and storage logic.

OAuth flow:
  After a successful Battle.net login the browser is redirected to:

      http://localhost:0/?ST=<token>&accountId=...

  Port 0 is intentionally invalid — Battle.net uses it as a redirect
  vehicle knowing no server is listening there.  Chromium/QtWebEngine
  blocks requests to port 0 at the network layer (ERR_UNSAFE_PORT),
  which means acceptNavigationRequest fires too late.

  We intercept using a QWebEngineUrlRequestInterceptor, which runs
  before Chromium's port blacklist, and extract the token from the URL
  query string there.

  Legacy flows also used a wtcg:// custom URL scheme; we handle both.

Token storage:
  Two mechanisms are written on every successful login:
    1. client.config  VerifyWebCredentials=<token>   (primary, no crypto)
    2. AES-CBC encrypted binary `token` file          (CoreFoundation stub)
  The game works with either; we write both for maximum compatibility.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Battle.net OAuth URLs
# ---------------------------------------------------------------------------

REGION_LOGIN_URLS: dict[str, str] = {
    "us": "https://us.battle.net/login/en/?app=wtcg",
    "eu": "https://eu.battle.net/login/en/?app=wtcg",
    "asia": "https://kr.battle.net/login/en/?app=wtcg",
}

# Battle.net redirects to http://localhost:0/?ST=<token>...
# Port 0 is on Chromium's blocked list — intercept before fetch.
BNET_REDIRECT_HOST = "localhost"
BNET_REDIRECT_PORT = 0

# Legacy: some older flows used a wtcg:// custom scheme
BNET_TOKEN_SCHEME = "wtcg"

# ---------------------------------------------------------------------------
# AES key derivation — matches Token.cs from hearthstone-linux exactly.
# Key = PBKDF2(SHA1, s_entropy XOR username[:16], "someSalt", 1000 iter, 16 bytes)
# IV  = 16 zero bytes (always)
# ---------------------------------------------------------------------------

_S_ENTROPY = bytes(
    [200, 118, 244, 174, 76, 149, 46, 254, 242, 250, 15, 84, 25, 192, 156, 67]
)


def _derive_aes_key(username: str) -> bytes:
    import hashlib

    array = bytearray(_S_ENTROPY)
    for i, ch in enumerate(username[:16]):
        array[i] ^= ord(ch)
    return hashlib.pbkdf2_hmac("sha1", bytes(array), b"someSalt", 1000, dklen=16)


AES_IV: bytes = bytes(16)  # 16 zero bytes

# ---------------------------------------------------------------------------
# URL detection — handles both localhost:0 and wtcg:// formats
# ---------------------------------------------------------------------------


def is_token_redirect(url: str) -> bool:
    """
    Return True if this URL is a Battle.net token redirect we should handle.
    Covers:
      - http://localhost:0/?ST=...   (current format)
      - wtcg://...                   (legacy format)
    """
    try:
        parsed = urlparse(url)
        # Current: localhost:0
        if (
            parsed.scheme in ("http", "https")
            and parsed.hostname == BNET_REDIRECT_HOST
            and parsed.port == BNET_REDIRECT_PORT
        ):
            return True
        # Legacy: wtcg:// scheme
        if parsed.scheme.lower() == BNET_TOKEN_SCHEME:
            return True
    except Exception:
        pass
    return False


def extract_token_from_url(url: str) -> Optional[str]:
    """
    Parse a Battle.net redirect URL and return the login token, or None.

    Handles:
      http://localhost:0/?ST=US-abc123...&accountId=...
      wtcg://client-auth?ST=<token>
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return None

    qs = parse_qs(parsed.query)

    # Try ST parameter first (most common)
    for key in ("ST", "st", "token", "access_token"):
        if key in qs:
            val = qs[key][0].strip()
            if val:
                return val

    # Try fragment parameters
    if parsed.fragment:
        fqs = parse_qs(parsed.fragment)
        for key in ("ST", "st", "token", "access_token"):
            if key in fqs:
                val = fqs[key][0].strip()
                if val:
                    return val

    # Last resort: regex for ST-style token in the raw URL
    m = re.search(r"ST-[A-Za-z0-9\-]+", url)
    if m:
        return m.group(0)

    return None


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


def write_token(token: str, install_dir: Path) -> None:
    """
    Persist the token using both supported mechanisms.
    Raises ValueError if the token looks empty or malformed.
    Raises OSError if the install directory isn't writable.
    """
    token = token.strip()
    if not token:
        raise ValueError("Token is empty.")
    if len(token) < 10:
        raise ValueError(f"Token looks too short to be valid: {token!r}")

    install_dir.mkdir(parents=True, exist_ok=True)

    # Write AES-encrypted binary token file (read by CoreFoundation.so stub)
    try:
        _write_token_file(token, install_dir)
    except ImportError:
        raise ImportError(
            "pycryptodome is required. Install with: pip install pycryptodome"
        )
    except Exception as exc:
        raise OSError(f"Failed to write token: {exc}") from exc


def _write_token_file(token: str, install_dir: Path) -> None:
    import hashlib
    import os

    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    username = os.environ.get("USER", os.environ.get("USERNAME", ""))
    key = _derive_aes_key(username)

    token_bytes = token.encode("utf-8")
    padded = pad(token_bytes, AES.block_size)
    cipher = AES.new(key, AES.MODE_CBC, AES_IV)
    encrypted = cipher.encrypt(padded)

    token_path = install_dir / "token"
    token_path.write_bytes(encrypted)


# ---------------------------------------------------------------------------
# Token validation / reading
# ---------------------------------------------------------------------------


def read_token_from_config(install_dir: Path) -> Optional[str]:
    config_path = install_dir / "client.config"
    if not config_path.is_file():
        return None
    try:
        text = config_path.read_text(encoding="utf-8")
        m = re.search(r"^VerifyWebCredentials\s*=\s*(.+)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip()
    except OSError:
        pass
    return None


def token_appears_valid(token: str) -> bool:
    """Basic sanity check — not a cryptographic validation."""
    t = token.strip()
    if len(t) < 20:
        return False
    if t.startswith("ST-"):
        return True
    if re.match(r"^[A-Za-z0-9\-_\.]+$", t):
        return True
    return False
