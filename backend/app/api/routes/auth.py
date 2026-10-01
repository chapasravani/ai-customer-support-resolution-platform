import collections
import os
import threading
import time
from fastapi import APIRouter, Depends, HTTPException, Request

from backend.app.core import security
from backend.app.domains import models
from backend.app.api.schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from backend.app.core.deps import get_current_user

LOGIN_RATE_LIMIT_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_ATTEMPTS", "10"))
LOGIN_RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60"))
LOGIN_RATE_LIMIT_IP_ATTEMPTS = int(os.getenv("LOGIN_RATE_LIMIT_IP_ATTEMPTS", "20"))
LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS = int(os.getenv("LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS", "300"))

_login_attempts: dict[str, list[float]] = collections.defaultdict(list)
_login_lock = threading.Lock()


def reset_login_rate_limits() -> None:
    """Reset login rate limiting data (useful for test isolation)."""
    with _login_lock:
        _login_attempts.clear()


def _check_login_rate_limit(client_ip: str, email: str) -> None:
    now = time.time()
    normalized_email = email.strip().lower()
    keys = (
        (f"email:{client_ip}:{normalized_email}", LOGIN_RATE_LIMIT_ATTEMPTS, LOGIN_RATE_LIMIT_WINDOW_SECONDS),
        (f"ip:{client_ip}", LOGIN_RATE_LIMIT_IP_ATTEMPTS, LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS),
    )
    with _login_lock:
        for stale_key, values in list(_login_attempts.items()):
            key_window = LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS if stale_key.startswith("ip:") else LOGIN_RATE_LIMIT_WINDOW_SECONDS
            remaining = [timestamp for timestamp in values if timestamp > now - key_window]
            if remaining:
                _login_attempts[stale_key] = remaining
            else:
                del _login_attempts[stale_key]

        for key, limit, window in keys:
            timestamps = [timestamp for timestamp in _login_attempts.get(key, []) if timestamp > now - window]
            if len(timestamps) >= limit:
                retry_after = int(timestamps[0] + window - now) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many login attempts. Please wait a moment before trying again.",
                    headers={"Retry-After": str(max(1, retry_after))},
                )

        for key, _, _ in keys:
            _login_attempts[key].append(now)


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=202)
def register(payload: RegisterRequest):
    if payload.role and payload.role.strip().lower() == "admin":
        raise HTTPException(
            400,
            "Registration with admin role is prohibited. Admin accounts must be created using scripts/manage_admin.py."
        )

    clean_email = payload.email.strip().lower()
    try:
        if not models.get_user_by_email(clean_email):
            hashed = security.hash_password(payload.password)
            models.create_user(
                email=clean_email,
                hashed_password=hashed,
                name=payload.name.strip(),
                role="customer",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Database service is temporarily unavailable. Please try again later.")

    return {"detail": "If this email can be registered, you can now log in."}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request):
    client_ip = request.client.host if request.client else "unknown"
    # Add a trusted-proxy header only when proxy trust is configured at deploy time.
    _check_login_rate_limit(client_ip, payload.email)

    try:
        user = models.get_user_by_email(payload.email)
    except Exception as exc:
        raise HTTPException(503, "Database service is temporarily unavailable. Please try again later.")

    if not user or not security.verify_password(payload.password, user.get("hashed_password")):
        raise HTTPException(401, "Incorrect email or password.")

    token = security.create_access_token(user_id=str(user["_id"]), role=user["role"])
    return TokenResponse(access_token=token, role=user["role"])


@router.get("/me", response_model=UserResponse)
def me(user: dict = Depends(get_current_user)):
    customer_id = models.get_customer_id_for_user(user)
    return UserResponse(
        id=str(user["_id"]),
        email=user["email"],
        name=user["name"],
        role=user["role"],
        customer_id=customer_id,
    )
