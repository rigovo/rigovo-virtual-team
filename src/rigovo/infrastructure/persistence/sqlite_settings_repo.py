"""SQLite settings repository — encrypted key/value store for runtime config.

Stores API keys, default model, endpoint URLs, and other settings that
the user configures via the desktop UI.

Security model:
- API keys are encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256).
- The encryption key is stored in the OS keychain via ``keyring``.
- If keyring is unavailable (headless Linux, CI), falls back to a
  machine-derived key (PBKDF2 of hostname+username+random salt in DB).
- Non-secret values (model names, URLs) are stored in plain text.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import platform
import secrets
from typing import Any

logger = logging.getLogger(__name__)

# Keys that contain secrets — MUST be encrypted at rest
SECRET_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "WORKOS_API_KEY",
    }
)

SETTINGS_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    encrypted  INTEGER DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

_KEYRING_SERVICE = "rigovo-desktop"
_KEYRING_ACCOUNT = "settings-encryption-key"


def _get_or_create_fernet_key(db: Any) -> bytes:
    """Obtain the Fernet encryption key.

    1. OS keychain via ``keyring`` (preferred — hardware-backed on macOS).
    2. Machine-derived key with a random salt persisted in the DB (fallback).
    """
    # ── Try OS keychain first ──
    try:
        import keyring as kr

        stored = kr.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
        if stored:
            return stored.encode()

        from cryptography.fernet import Fernet

        key = Fernet.generate_key()
        kr.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, key.decode())
        logger.info("Encryption key stored in OS keychain")
        return key
    except Exception as exc:
        logger.debug("Keychain unavailable (%s), using machine-derived key", exc)

    # ── Fallback: PBKDF2 with random salt in DB ──
    row = db.fetchone("SELECT value FROM settings WHERE key = ?", ("_encryption_salt",))
    if row:
        salt = bytes.fromhex(row["value"])
    else:
        salt = secrets.token_bytes(32)
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value, encrypted, updated_at) "
            "VALUES (?, ?, 0, datetime('now'))",
            ("_encryption_salt", salt.hex()),
        )
        db.commit()

    try:
        login = os.getlogin()
    except OSError:
        login = os.environ.get("USER", "rigovo")

    machine_id = f"{platform.node()}:{login}:rigovo-v1"
    dk = hashlib.pbkdf2_hmac("sha256", machine_id.encode(), salt, iterations=480_000, dklen=32)
    return base64.urlsafe_b64encode(dk)


class SqliteSettingsRepository:
    """Encrypted key/value store backed by SQLite.

    Secret values (API keys) → encrypted with Fernet before storage.
    Non-secret values (model names, URLs) → plain text.
    """

    def __init__(self, db: Any) -> None:
        self._db = db
        self._ensure_table()
        self._fernet = self._init_fernet()

    # ── public API ──────────────────────────────────────────────────

    def get(self, key: str, default: str = "") -> str:
        row = self._db.fetchone("SELECT value, encrypted FROM settings WHERE key = ?", (key,))
        if not row:
            return default
        return self._decrypt(row["value"]) if row["encrypted"] else row["value"]

    def get_many(self, keys: list[str]) -> dict[str, str]:
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        rows = self._db.fetchall(
            f"SELECT key, value, encrypted FROM settings WHERE key IN ({placeholders})",
            tuple(keys),
        )
        result: dict[str, str] = {}
        for row in rows:
            result[row["key"]] = self._decrypt(row["value"]) if row["encrypted"] else row["value"]
        for k in keys:
            result.setdefault(k, "")
        return result

    def get_all(self) -> dict[str, str]:
        rows = self._db.fetchall(
            "SELECT key, value, encrypted FROM settings WHERE key != '_encryption_salt'"
        )
        result: dict[str, str] = {}
        for row in rows:
            result[row["key"]] = self._decrypt(row["value"]) if row["encrypted"] else row["value"]
        return result

    def set(self, key: str, value: str) -> None:
        is_secret = key in SECRET_KEYS
        stored = self._encrypt(value) if is_secret else value
        self._db.execute(
            "INSERT INTO settings (key, value, encrypted, updated_at) "
            "VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "encrypted=excluded.encrypted, updated_at=excluded.updated_at",
            (key, stored, 1 if is_secret else 0),
        )
        self._db.commit()

    def set_many(self, items: dict[str, str]) -> None:
        if not items:
            return
        for key, value in items.items():
            is_secret = key in SECRET_KEYS
            stored = self._encrypt(value) if is_secret else value
            self._db.execute(
                "INSERT INTO settings (key, value, encrypted, updated_at) "
                "VALUES (?, ?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "encrypted=excluded.encrypted, updated_at=excluded.updated_at",
                (key, stored, 1 if is_secret else 0),
            )
        self._db.commit()

    def delete(self, key: str) -> None:
        self._db.execute("DELETE FROM settings WHERE key = ?", (key,))
        self._db.commit()

    # ── encryption internals ────────────────────────────────────────

    def _init_fernet(self):
        try:
            from cryptography.fernet import Fernet

            key = _get_or_create_fernet_key(self._db)
            return Fernet(key)
        except Exception as exc:
            logger.warning("Encryption init failed: %s — secrets stored plain", exc)
            return None

    def _encrypt(self, plaintext: str) -> str:
        if not self._fernet or not plaintext:
            return plaintext
        try:
            return self._fernet.encrypt(plaintext.encode()).decode()
        except Exception:
            logger.warning("Encryption failed, storing plain")
            return plaintext

    def _decrypt(self, ciphertext: str) -> str:
        if not self._fernet or not ciphertext:
            return ciphertext
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except Exception:
            logger.debug("Decryption failed — returning raw value")
            return ciphertext

    # ── table setup ─────────────────────────────────────────────────

    def _ensure_table(self) -> None:
        try:
            self._db.execute(SETTINGS_TABLE_SQL)
            self._db.commit()
        except Exception:
            logger.debug("Settings table already exists")
