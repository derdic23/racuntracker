"""Encrypts secrets stored in the database (Gmail app password) with a key derived from SECRET_KEY."""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet(secret_key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))


def encrypt(secret_key: str, text: str) -> str:
    return _fernet(secret_key).encrypt(text.encode()).decode()


def decrypt(secret_key: str, token: str) -> str | None:
    """None if the token was encrypted with a different SECRET_KEY."""
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except InvalidToken:
        return None
