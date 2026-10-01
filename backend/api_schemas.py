"""
Pydantic request/response shapes for the FastAPI routes.

Not to be confused with backend/models.py, which holds the MongoDB
create/read/update functions. This file only validates what comes in
over HTTP and shapes what goes back out.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class TicketStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    CLOSED = "closed"
    IN_PROGRESS = "in_progress"


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    name: str
    role: Optional[str] = "customer"


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
    customer_id: Optional[str] = None


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[str] = None
    request_id: Optional[str] = None


class ChatMessageResponse(BaseModel):
    conversation_id: str
    response: str
    error: Optional[bool] = None
    error_type: Optional[str] = None
    deduplicated: Optional[bool] = None


class ActionReviewRequest(BaseModel):
    status: str = Field(..., pattern="^(approved|rejected)$")
    reason: Optional[str] = ""


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=80)


class FeedbackRequest(BaseModel):
    conversation_id: str
    rating: str = Field(pattern="^(like|dislike)$")
    message_index: Optional[int] = None


class TicketStatusUpdate(BaseModel):
    status: TicketStatus
    resolution_summary: Optional[str] = ""


class ModelInfoResponse(BaseModel):
    provider: str
    provider_display: str
    model: str
    fallback_model: str
    display_name: str


class HealthResponse(BaseModel):
    status: str
    storage_type: str
    mongodb_connected: bool
    persistent_fallback_active: bool
    rag: str
    details: Optional[str] = None
