"""
FastAPI dependencies for "who is calling this route".

get_current_user   -> any logged-in user (customer or admin)
require_admin      -> only an admin
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import auth, models

bearer_scheme = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    payload = auth.decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid or expired token."
        )

    user = models.get_user_by_id(payload["sub"])
    if not user:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "This account no longer exists."
        )

    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Admin access required."
        )
    return user
