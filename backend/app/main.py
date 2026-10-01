"""
FastAPI application entry point.

Run with:
    uvicorn backend.app.main:app --reload
(from the repository root)
"""

import os
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.app.workflows.support_agent.agent import DEFAULT_FALLBACK_MODEL, DEFAULT_PRIMARY_MODEL

from backend.app.core import security
from backend.app.infrastructure import db
from backend.app.api.schemas import HealthResponse, ModelInfoResponse
from backend.app.rag.retriever import collection_count
from backend.app.api.routes import admin, auth, chat, documents, tickets

PROVIDER_NAMES: Dict[str, str] = {
    "gemini": "Google Gemini",
    "groq": "Groq",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "anthropic": "Anthropic",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # C7: Validate JWT secret at startup (fails fast if unset, too short, or placeholder)
    security.get_jwt_secret()
    # Ensure indexes on startup
    db.ensure_indexes()
    yield


app = FastAPI(
    title="AI Customer Support & Resolution Platform API",
    lifespan=lifespan,
)

cors_origins_env = os.getenv("CORS_ORIGINS", "")
if cors_origins_env.strip():
    allowed_origins = [orig.strip() for orig in cors_origins_env.split(",") if orig.strip()]
else:
    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse)
def health() -> dict:
    """Return system health and storage status, clearly distinguishing MongoDB from local fallback."""
    status = db.get_storage_info()
    status["rag"] = "unavailable" if collection_count() is None else "available"
    return status


@app.get("/system/model-info", response_model=ModelInfoResponse)
def model_info() -> dict:
    """Return the active AI provider, model names, and display branding."""
    try:
        from backend.app.workflows.support_agent import agent as fcs_agent
        primary_model = getattr(fcs_agent, "MODEL_NAME", os.getenv("MODEL", DEFAULT_PRIMARY_MODEL))
        fallback_model = getattr(fcs_agent, "FALLBACK_MODEL_NAME", os.getenv("FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL))
    except Exception:
        primary_model = os.getenv("MODEL", DEFAULT_PRIMARY_MODEL)
        fallback_model = os.getenv("FALLBACK_MODEL", DEFAULT_FALLBACK_MODEL)

    provider = os.getenv("PROVIDER", "gemini").lower()
    provider_display = PROVIDER_NAMES.get(provider, provider.title())

    return {
        "provider": provider,
        "provider_display": provider_display,
        "model": primary_model,
        "fallback_model": fallback_model,
        "display_name": f"{provider_display} — {primary_model}",
    }


app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(tickets.router)
app.include_router(documents.router)
app.include_router(admin.router)
