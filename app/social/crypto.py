"""Symmetric encryption for social-platform OAuth tokens at rest.

These are real credentials to a user's own social account — categorically
more sensitive than this app's own API keys (which grant access to Culturix's
resources, not a user's), so they're encrypted in the DB rather than stored
as plain text like every other credential in this codebase."""
import os
from functools import lru_cache
from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY not set — generate one with "
            "`python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"`"
        )
    return Fernet(key.encode())


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()
