"""Password hashing helpers for operator-provisioned team accounts."""
import base64
import hashlib
import hmac
import secrets


_N = 1 << 14
_R = 8
_P = 1
_LENGTH = 32
_MIN_LENGTH = 12
_MAX_LENGTH = 1024


def hash_password(password: str) -> str:
    if not _MIN_LENGTH <= len(password) <= _MAX_LENGTH:
        raise ValueError(f"Password must be between {_MIN_LENGTH} and {_MAX_LENGTH} characters.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_LENGTH)
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    digest_text = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"scrypt${_N}${_R}${_P}${salt_text}${digest_text}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or len(password) > _MAX_LENGTH:
        return False
    try:
        algorithm, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$", 5)
        n, r, p = int(n_text), int(r_text), int(p_text)
        if algorithm != "scrypt" or n != _N or r != _R or p != _P:
            return False
        salt = base64.urlsafe_b64decode(salt_text + "=" * (-len(salt_text) % 4))
        expected = base64.urlsafe_b64decode(digest_text + "=" * (-len(digest_text) % 4))
        if len(salt) != 16 or len(expected) != _LENGTH:
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_LENGTH)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False
