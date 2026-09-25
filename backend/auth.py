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

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRES_MINUTES = int(os.getenv("JWT_EXPIRES_MINUTES", "480"))  # 8 hours


def hash_password(plain_password: str) -> str:
    """Hash a plain-text password for storage. Never store plain_password itself."""
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a login attempt's password against the stored hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def create_access_token(user_id: str, role: str) -> str:
    """Create a signed JWT that /auth/me and every protected route will check."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[dict]:
    """Return the token's payload if valid, or None if it's invalid/expired."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
