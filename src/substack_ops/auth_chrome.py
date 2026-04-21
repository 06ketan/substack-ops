"""Auto-grab Substack cookies from Chrome / Brave on macOS.

macOS encrypts cookie values with a key stored in the Keychain ("Chrome Safe
Storage"). On first run the user gets a Keychain prompt. We extract just the
two cookies we care about (`substack.sid` + `substack.lli`) and write them in
the same JSON shape `_substack/auth.py` expects.

Optional dep: `pycryptodome` + `keyring`. Falls back to a clear error message.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

CHROME_COOKIES = Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "Default" / "Cookies"
BRAVE_COOKIES = Path.home() / "Library" / "Application Support" / "BraveSoftware" / "Brave-Browser" / "Default" / "Cookies"


def _decrypt(value: bytes, key: bytes) -> str:
    from Crypto.Cipher import AES  # type: ignore[import-untyped]

    if value[:3] == b"v10":
        ciphertext = value[3:]
        iv = b" " * 16
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(ciphertext)
        pad = decrypted[-1]
        return decrypted[:-pad].decode("utf-8", errors="replace")
    return value.decode("utf-8", errors="replace")


def _derive_key(safe_storage_password: str) -> bytes:
    from Crypto.Protocol.KDF import PBKDF2  # type: ignore[import-untyped]
    from Crypto.Hash import SHA1  # type: ignore[import-untyped]

    return PBKDF2(
        safe_storage_password.encode("utf-8"),
        b"saltysalt",
        16,
        count=1003,
        hmac_hash_module=SHA1,
    )


def grab_cookies(
    browser: str = "chrome",
    out_path: Path | None = None,
) -> Path:
    """Read Substack cookies from Chrome/Brave and write them to `out_path`.

    Raises RuntimeError with a clear message if deps are missing or browser is
    closed-locked.
    """
    if sys.platform != "darwin":
        raise RuntimeError("auth_chrome currently supports macOS only.")

    try:
        import keyring  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError(
            "Missing deps: install with `uv pip install 'substack-ops[chrome]'`."
        ) from exc

    src = {"chrome": CHROME_COOKIES, "brave": BRAVE_COOKIES}.get(browser.lower())
    if not src or not src.exists():
        raise RuntimeError(f"Cookie store not found at {src}")

    keychain_service = {
        "chrome": "Chrome Safe Storage",
        "brave": "Brave Safe Storage",
    }[browser.lower()]
    pwd = keyring.get_password(keychain_service, browser.title())
    if not pwd:
        raise RuntimeError(
            f"Could not read {keychain_service} from Keychain. "
            f"Open Keychain Access, find {keychain_service!r}, and click 'Always Allow'."
        )
    key = _derive_key(pwd)

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        tmp = Path(tf.name)
    try:
        shutil.copy2(src, tmp)
        conn = sqlite3.connect(tmp)
        cur = conn.execute(
            "SELECT name, encrypted_value FROM cookies "
            "WHERE host_key LIKE '%substack.com'"
        )
        wanted = {"substack.sid", "substack.lli"}
        out: list[dict[str, Any]] = []
        for name, blob in cur.fetchall():
            if name not in wanted:
                continue
            try:
                value = _decrypt(blob, key)
            except Exception as exc:
                raise RuntimeError(f"decrypt failed for {name}: {exc}") from exc
            out.append(
                {
                    "name": name,
                    "value": value,
                    "domain": ".substack.com",
                    "path": "/",
                    "secure": True,
                }
            )
        conn.close()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    if not out:
        raise RuntimeError(
            f"No substack.* cookies found in {browser}. Log in at substack.com first."
        )

    out_path = out_path or (Path(".cache") / "cookies.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2))
    try:
        os.chmod(out_path, 0o600)
    except OSError:
        pass
    return out_path
