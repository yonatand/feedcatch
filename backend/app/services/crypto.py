"""Fernet encryption for stored secrets (qBittorrent password).

Key source: APP_SECRET_KEY env (any string; a Fernet key is derived via SHA-256) else `{data_dir}/secret.key`
(generated with mode 0600 on first use). The same key material also seeds the session-cookie signer.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings, get_settings

SECRET_FILE_NAME = "secret.key"


class CryptoError(Exception):
    """Decryption failed (wrong key or corrupted value)."""


def _key_file(settings: Settings) -> Path:
    return settings.data_dir / SECRET_FILE_NAME


def _load_or_create_file_key(settings: Settings) -> bytes:
    path = _key_file(settings)
    if path.exists():
        return path.read_bytes().strip()
    settings.ensure_data_dir()
    key = Fernet.generate_key()
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:  # created concurrently
        return path.read_bytes().strip()
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    with contextlib.suppress(OSError):  # e.g. some Windows filesystems
        os.chmod(path, 0o600)
    return key


def get_key_material(settings: Settings | None = None) -> bytes:
    """Return the urlsafe-base64 32-byte Fernet key."""
    s = settings or get_settings()
    if s.APP_SECRET_KEY:
        digest = hashlib.sha256(s.APP_SECRET_KEY.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)
    return _load_or_create_file_key(s)


def get_fernet(settings: Settings | None = None) -> Fernet:
    return Fernet(get_key_material(settings))


def encrypt(value: str, settings: Settings | None = None) -> str:
    return get_fernet(settings).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str, settings: Settings | None = None) -> str:
    try:
        return get_fernet(settings).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CryptoError("could not decrypt stored secret (secret key changed?)") from exc
