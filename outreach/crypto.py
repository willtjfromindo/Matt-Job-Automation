"""Encrypt/decrypt the Google refresh token.

Format (shared with web/lib/crypto.ts): base64( iv[12] || ciphertext || tag[16] ), AES-256-GCM,
key = base64-decoded TOKEN_ENCRYPTION_KEY (32 bytes).
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key(b64_key: str) -> bytes:
    key = base64.b64decode(b64_key or "")
    if len(key) != 32:
        raise ValueError("TOKEN_ENCRYPTION_KEY must be base64 of exactly 32 bytes")
    return key


def encrypt(plaintext: str, b64_key: str) -> str:
    iv = os.urandom(12)
    sealed = AESGCM(_key(b64_key)).encrypt(iv, plaintext.encode(), None)
    return base64.b64encode(iv + sealed).decode()


def decrypt(token: str, b64_key: str) -> str:
    raw = base64.b64decode(token)
    return AESGCM(_key(b64_key)).decrypt(raw[:12], raw[12:], None).decode()
