from fastapi import APIRouter, Depends, HTTPException

from .. import auth, models
from ..api_schemas import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from ..deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest):
    if payload.role and payload.role.strip().lower() == "admin":
        raise HTTPException(
            400,
            "Registration with admin role is prohibited. Admin accounts must be created using backend/manage_admin.py."
        )

    clean_email = payload.email.strip().lower()
    try:
        if models.get_user_by_email(clean_email):
            raise HTTPException(400, "An account with this email already exists.")

        hashed = auth.hash_password(payload.password)
        user = models.create_user(
            email=clean_email,
            hashed_password=hashed,
            name=payload.name.strip(),
            role="customer",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "Database service is temporarily unavailable. Please try again later.")

    token = auth.create_access_token(user_id=str(user["_id"]), role="customer")
    return TokenResponse(access_token=token, role="customer")


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    try:
        user = models.get_user_by_email(payload.email)
    except Exception as exc:
        raise HTTPException(503, "Database service is temporarily unavailable. Please try again later.")

    if not user or not auth.verify_password(payload.password, user.get("hashed_password")):
        raise HTTPException(401, "Incorrect email or password.")

    token = auth.create_access_token(user_id=str(user["_id"]), role=user["role"])
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
