"""Cryptographic primitives. No credentials are logged or embedded in this module."""
import base64
import hashlib
import hmac
import re
import secrets
from uuid import UUID

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PASSWORDS = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))


def token_hash(kind: str, value: str) -> str:
    return hashlib.sha256((kind + ":" + value).encode()).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)


def normalize_phone(value: str) -> str:
    cleaned = re.sub(r"[ ()-]", "", value)
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif len(cleaned) == 12 and cleaned.startswith("91"):
        cleaned = cleaned[2:]
    if not re.fullmatch(r"[6-9][0-9]{9}", cleaned):
        raise ValueError("Enter a valid Indian mobile number")
    return "+91" + cleaned


def check_password_policy(password: str) -> None:
    if not (12 <= len(password) <= 128 and any(c.isalpha() for c in password)
            and any(not c.isalpha() and not c.isspace() for c in password)):
        raise ValueError("Password needs 12–128 characters, a letter and a digit or symbol")
    if any(word in password.casefold() for word in ("password", "qwerty", "letmein", "123456", "offlinewallet")):
        raise ValueError("Choose a password without common password patterns")


def verify_password(encoded: str | None, password: str) -> bool:
    try:
        valid = PASSWORDS.verify(encoded or DUMMY_HASH, password)
        return bool(encoded) and valid
    except (VerificationError, InvalidHashError):
        return False


class DeviceCipher:
    def __init__(self, key: str):
        try:
            decoded = base64.b64decode(key, altchars=b"-_", validate=True)
            if len(decoded) != 32:
                raise ValueError()
        except (ValueError, TypeError):
            raise ValueError("DEVICE_MASTER_KEY must encode exactly 32 random bytes") from None
        self._cipher = AESGCM(decoded)

    @staticmethod
    def _aad(device: UUID, participant: UUID, version: int) -> bytes:
        return f"offlinewallet-device-v1:{device}:{participant}:{version}".encode()

    def encrypt(self, secret: str, device: UUID, participant: UUID, version: int) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + self._cipher.encrypt(nonce, secret.encode(), self._aad(device, participant, version))

    def matches(self, encrypted: bytes, secret: str, device: UUID, participant: UUID, version: int) -> bool:
        try:
            actual = self._cipher.decrypt(encrypted[:12], encrypted[12:], self._aad(device, participant, version))
            return hmac.compare_digest(actual, secret.encode())
        except (InvalidTag, ValueError):
            return False
