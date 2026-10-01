"""
Password hashing and JWT helpers.

This is the ONLY file that should import bcrypt or jwt directly - every
other file asks this module to hash/verify a password or create/check a
token, instead of doing that itself. That keeps all the "how do we prove
who this user is" logic in one place.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

INSECURE_DEFAULT_SECRET = "dev-only-secret-change-me"
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "480"))  # 8 hours


def get_jwt_secret() -> str:
    """
    Retrieve and validate the JWT secret from environment.
    Never exposes or logs the actual secret.
    Fails safely if missing, shorter than 32 chars, or if the insecure placeholder is used.
    """
    secret = (os.getenv("JWT_SECRET") or "").strip()
    if not secret:
        raise RuntimeError(
            "JWT_SECRET is not configured. Please define a secure JWT_SECRET (minimum 32 characters) in your environment or backend/.env."
        )

    normalized = secret.lower()
    is_placeholder = normalized.startswith(("replace_with", "changeme", "your_")) or "placeholder" in normalized
    if secret == INSECURE_DEFAULT_SECRET or len(secret) < 32 or is_placeholder:
        raise RuntimeError(
            "Insecure or placeholder JWT_SECRET cannot be used. "
            "Please configure a cryptographically secure secret of at least 32 characters."
        )

    return secret


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password for storage. Never store plain_password itself."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a login attempt's password against the stored hash."""
    if not plain_password or not hashed_password or not isinstance(hashed_password, str):
        return False
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: str, role: str) -> str:
    """Create a signed JWT that /auth/me and every protected route will check."""
    secret = get_jwt_secret()
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Return the token's payload if valid, or None if it's invalid/expired."""
    try:
        secret = get_jwt_secret()
        return jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except (jwt.PyJWTError, RuntimeError):
        return None
