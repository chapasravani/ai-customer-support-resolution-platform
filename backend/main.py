"""
FastAPI application entry point.

Run with:
    uvicorn backend.main:app --reload
(from the project root - the folder that CONTAINS both
final_customer_support/ and backend/)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .routes import auth, chat, documents, tickets

app = FastAPI(title="AI Customer Support & Resolution Platform API")

# Allows the separate HTML/CSS/JS frontend (Phase 4/7, served from a
# different origin/port) to call this API. Before deploying anywhere
# public, replace "*" with your actual frontend URL(s).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    db.ensure_indexes()


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mongodb_connected": db.check_connection()}


@app.get("/system/model-info")
def model_info() -> dict:
    import os
    try:
        from final_customer_support import agent as fcs_agent
        primary_model = getattr(fcs_agent, "MODEL_NAME", os.getenv("MODEL", "gemini-3.5-flash-lite"))
        fallback_model = getattr(fcs_agent, "FALLBACK_MODEL_NAME", os.getenv("FALLBACK_MODEL", "gemini-3.1-flash-lite"))
    except Exception:
        primary_model = os.getenv("MODEL", "gemini-3.5-flash-lite")
        fallback_model = os.getenv("FALLBACK_MODEL", "gemini-3.1-flash-lite")

    provider = os.getenv("PROVIDER", "gemini").lower()
    provider_names = {
        "gemini": "Google Gemini",
        "groq": "Groq",
        "openai": "OpenAI",
        "openrouter": "OpenRouter",
        "anthropic": "Anthropic",
    }
    provider_display = provider_names.get(provider, provider.title())

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
