from fastapi import APIRouter, Depends, HTTPException

from .. import auth, models
from ..api_schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from ..deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest):
    if models.get_user_by_email(payload.email):
        raise HTTPException(400, "An account with this email already exists.")

    hashed = auth.hash_password(payload.password)
    user = models.create_user(
        email=payload.email,
        hashed_password=hashed,
        name=payload.name,
        role=payload.role,
    )
    token = auth.create_access_token(user_id=str(user["_id"]), role=user["role"])
    return TokenResponse(access_token=token, role=user["role"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    user = models.get_user_by_email(payload.email)
    if not user or not auth.verify_password(payload.password, user["hashed_password"]):
        raise HTTPException(401, "Incorrect email or password.")

    token = auth.create_access_token(user_id=str(user["_id"]), role=user["role"])
    return TokenResponse(access_token=token, role=user["role"])


@router.get("/me", response_model=UserResponse)
def me(user: dict = Depends(get_current_user)):
    return UserResponse(
        id=str(user["_id"]),
        email=user["email"],
        name=user["name"],
        role=user["role"],
    )
