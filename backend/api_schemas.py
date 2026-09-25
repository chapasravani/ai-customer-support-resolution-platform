"""
Pydantic request/response shapes for the FastAPI routes.

Not to be confused with backend/models.py, which holds the MongoDB
create/read/update functions. This file only validates what comes in
over HTTP and shapes what goes back out.
"""

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    name: str
    role: str = Field(default="customer", pattern="^(customer|admin)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: Optional[str] = None


class ChatMessageResponse(BaseModel):
    conversation_id: str
    response: str


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class TicketStatusUpdate(BaseModel):
    status: str
    resolution_summary: Optional[str] = ""
