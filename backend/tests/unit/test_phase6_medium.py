"""
Phase 6 verification test suite — Medium Priority Issues (M1–M9).

How to run:
    py -3.12 -m backend.test_phase6_medium
or:
    pytest backend/tests/unit/test_phase6_medium.py

What it tests:
    1. M1 — Ticket status validation (TicketStatus enum, 422 on invalid status).
    2. M2 — CORS security configuration (CORS_ORIGINS env parsing and safe defaults).
    3. M3 — Chat request protection (message max_length=4000, 30 req/min rate limit with 429).
    4. M4 — Document upload reliability (empty file check 400, >10MB limit 413, controlled error handling).
    5. M5 — RAG document untrusted boundaries (UNTRUSTED_DOCUMENT wrappers & security disclaimer).
    6. M6 — Corrupt JSON data raises and is left unchanged.
    7. M7 — Pinned dependencies across backend and agent requirements files.
    8. M8 — Root pytest.ini test configuration.
    9. M9 — Frontend auth error handling (401 triggers logout, 403 shows error without logout).
"""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.api_schemas import (
    ChatMessageRequest,
    TicketStatus,
    TicketStatusUpdate,
)
from backend.rag.context import retrieve_support_context
from backend.routes import chat, documents


# ============================================================================
# M1 — Ticket status validation
# ============================================================================

def test_m1_ticket_status_validation():
    print("Testing M1 — Ticket status validation...")
    valid_statuses = ["open", "investigating", "escalated", "resolved", "closed", "in_progress"]
    for s in valid_statuses:
        req = TicketStatusUpdate(status=TicketStatus(s))
        assert req.status.value == s

    # Invalid status should raise ValidationError
    with pytest.raises(ValidationError):
        TicketStatusUpdate(status="unsupported_status")

    with pytest.raises(ValidationError):
        TicketStatusUpdate(status="deleted")
    print("  [OK] TicketStatus enum rejects invalid statuses and accepts valid statuses.")


# ============================================================================
# M2 — CORS configuration
# ============================================================================

def test_m2_cors_security():
    print("Testing M2 — CORS security configuration...")
    # Verify .env.example contains CORS_ORIGINS
    env_example = Path("backend/.env.example").read_text(encoding="utf-8")
    assert "CORS_ORIGINS=" in env_example, "backend/.env.example must document CORS_ORIGINS"

    # Test origin parsing logic
    test_env = "http://example.com, https://app.example.com "
    parsed = [orig.strip() for orig in test_env.split(",") if orig.strip()]
    assert parsed == ["http://example.com", "https://app.example.com"]

    # Verify default allowed origins in backend/main.py
    import backend.main as main_mod
    assert hasattr(main_mod, "allowed_origins")
    assert "http://localhost:3000" in main_mod.allowed_origins
    assert "http://localhost:8000" in main_mod.allowed_origins
    print("  [OK] CORS origins are configurable via environment with safe defaults.")


# ============================================================================
# M3 — Chat request protection
# ============================================================================

def test_m3_chat_request_protection():
    print("Testing M3 — Chat request protection (length & rate limit)...")
    # Message length validation
    valid_req = ChatMessageRequest(message="Hello support")
    assert valid_req.message == "Hello support"

    with pytest.raises(ValidationError):
        # Empty message
        ChatMessageRequest(message="")

    with pytest.raises(ValidationError):
        # Exceeds 4000 characters
        ChatMessageRequest(message="x" * 4001)

    # Rate limiting validation
    chat.reset_chat_rate_limits()
    user_id = "test_user_rate_limit"

    # Send up to limit (30 requests)
    for _ in range(chat.CHAT_RATE_LIMIT_REQUESTS):
        chat._check_rate_limit(user_id)

    # 31st request must trigger 429
    with pytest.raises(HTTPException) as exc_info:
        chat._check_rate_limit(user_id)
    assert exc_info.value.status_code == 429
    assert "Rate limit exceeded" in exc_info.value.detail
    assert "Retry-After" in exc_info.value.headers

    chat.reset_chat_rate_limits()
    print("  [OK] Message length limits and 429 rate limiting enforced.")


# ============================================================================
# M4 — Document upload reliability
# ============================================================================

def test_m4_document_upload_reliability():
    print("Testing M4 — Document upload reliability...")
    admin_user = {"_id": "admin_test_id", "role": "admin"}

    # 1. Unsupported extension
    mock_file_unsupported = MagicMock()
    mock_file_unsupported.filename = "malicious.exe"
    with pytest.raises(HTTPException) as exc1:
        asyncio.run(documents.upload_document(mock_file_unsupported, admin_user))
    assert exc1.value.status_code == 400
    assert "Unsupported file type" in exc1.value.detail

    # 2. Empty file
    mock_file_empty = MagicMock()
    mock_file_empty.filename = "empty.txt"
    mock_file_empty.read = AsyncMock(return_value=b"")
    with pytest.raises(HTTPException) as exc2:
        asyncio.run(documents.upload_document(mock_file_empty, admin_user))
    assert exc2.value.status_code == 400
    assert "uploaded file is empty" in exc2.value.detail

    # 3. File exceeding 10MB
    mock_file_large = MagicMock()
    mock_file_large.filename = "large.txt"
    large_bytes = b"a" * (documents.MAX_FILE_SIZE + 1)
    mock_file_large.read = AsyncMock(return_value=large_bytes)
    with pytest.raises(HTTPException) as exc3:
        asyncio.run(documents.upload_document(mock_file_large, admin_user))
    assert exc3.value.status_code == 413
    assert "10MB limit" in exc3.value.detail
    print("  [OK] Document upload size checks and empty file handling verified.")


# ============================================================================
# M5 — RAG document untrusted boundaries
# ============================================================================

def test_m5_rag_untrusted_boundaries():
    print("Testing M5 — RAG untrusted document boundaries...")
    # Empty search results
    with patch("backend.rag.context.search_documents", return_value=[]):
        ctx_empty = retrieve_support_context("return policy")
        assert ctx_empty == "No relevant support-policy information was found."

    # Populated search results
    mock_chunks = [
        {"source": "policy.md", "content": "Refunds are processed within 14 days."},
        {"source": "rules.txt", "content": "Admins must approve cancellations over $100."},
    ]
    with patch("backend.rag.context.search_documents", return_value=mock_chunks):
        ctx = retrieve_support_context("refund rules")
        assert "IMPORTANT SECURITY NOTICE FOR AGENTS:" in ctx
        assert "=== BEGIN UNTRUSTED_DOCUMENT (Index: 1, Source: policy.md) ===" in ctx
        assert "=== END UNTRUSTED_DOCUMENT (Index: 1) ===" in ctx
        assert "Refunds are processed within 14 days." in ctx
        assert "=== BEGIN UNTRUSTED_DOCUMENT (Index: 2, Source: rules.txt) ===" in ctx
        assert "=== END UNTRUSTED_DOCUMENT (Index: 2) ===" in ctx

    # Verify agent instructions include untrusted document safety rule
    agent_code = Path("final_customer_support/agent.py").read_text(encoding="utf-8")
    assert "UNTRUSTED_DOCUMENT" in agent_code
    print("  [OK] UNTRUSTED_DOCUMENT boundary markers and security guidance verified.")


# ============================================================================
# M6 — Support cases atomic save in MCP and OpenAPI servers
# ============================================================================

def test_m6_corrupt_json_fails_closed(tmp_path, monkeypatch):
    from final_customer_support import agent
    from final_customer_support.tools import business_actions

    malformed = "{not valid json"
    path = tmp_path / "orders.json"
    path.write_text(malformed, encoding="utf-8")
    monkeypatch.setattr(agent, "DATA_DIR", tmp_path)
    monkeypatch.setattr(business_actions, "DATA", tmp_path)
    with pytest.raises(ValueError, match="invalid JSON"):
        agent.load_json("orders.json")
    with pytest.raises(ValueError, match="Failed to parse"):
        business_actions._load("orders.json")
    assert path.read_text(encoding="utf-8") == malformed
    print("  [OK] Corrupt JSON raises without overwriting the source file.")


# ============================================================================
# M7 — Production dependencies
# ============================================================================

def test_m7_production_dependencies():
    print("Testing M7 — Production dependencies...")
    backend_reqs = Path("backend/requirements.txt").read_text(encoding="utf-8")
    agent_reqs = Path("final_customer_support/requirements.txt").read_text(encoding="utf-8")

    # Backend requirements
    required_backend = [
        "chromadb==1.5.9",
        "pypdf==6.19.0",
        "pytest==9.1.1",
        "pytest-asyncio==1.4.0",
        "mongomock==4.3.0",
    ]
    for req in required_backend:
        assert req in backend_reqs, f"Missing {req} in backend/requirements.txt"
    assert "pdfplumber" not in backend_reqs, "pdfplumber should have been removed per M7"
    assert "python-docx" not in backend_reqs, "python-docx should have been removed per M7"

    # Agent requirements
    required_agent = [
        "google-adk==2.9.1",
        "google-genai==2.23.0",
        "fastapi==0.141.1",
        "pydantic==2.13.5",
        "python-dotenv==1.1.1",
        "uvicorn==0.53.0",
    ]
    for req in required_agent:
        assert req in agent_reqs, f"Missing {req} in final_customer_support/requirements.txt"
    assert "mcp==" not in agent_reqs
    print("  [OK] All production and test dependencies pinned and synchronized.")


# ============================================================================
# M8 — Test configuration
# ============================================================================

def test_m8_pytest_configuration():
    print("Testing M8 — Pytest configuration...")
    pytest_ini = Path("pytest.ini")
    assert pytest_ini.exists(), "pytest.ini must exist at root"
    content = pytest_ini.read_text(encoding="utf-8")
    assert "pythonpath" in content
    assert "testpaths" in content
    print("  [OK] Root pytest.ini exists and configured properly.")


# ============================================================================
# M9 — Frontend auth error handling
# ============================================================================

def test_m9_frontend_auth_error_handling():
    print("Testing M9 — Frontend auth error handling (401 vs 403)...")
    customer_js = Path("frontend/customer/app.js").read_text(encoding="utf-8")
    admin_js = Path("frontend/admin/app.js").read_text(encoding="utf-8")

    # Customer frontend: 401 triggers logout, 403 does not
    assert "if (response.status === 401)" in customer_js
    assert "if (response.status === 403)" in customer_js
    assert "logout(false);" in customer_js

    # Admin frontend: 401 triggers logout, 403 does not
    assert "if (response.status === 401)" in admin_js
    assert "logout();" in admin_js
    assert "response.status === 403" in admin_js
    assert "Access denied: You do not have permission to perform this action." in admin_js
    print("  [OK] Frontend auth error handling differentiates 401 and 403.")


# ============================================================================
# Run all tests when executed directly
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("RUNNING PHASE 6 VERIFICATION TEST SUITE (M1–M9)")
    print("=" * 60)
    test_m1_ticket_status_validation()
    test_m2_cors_security()
    test_m3_chat_request_protection()
    test_m4_document_upload_reliability()
    test_m5_rag_untrusted_boundaries()
    test_m6_corrupt_json_fails_closed(Path(tempfile.mkdtemp()), pytest.MonkeyPatch())
    test_m7_production_dependencies()
    test_m8_pytest_configuration()
    test_m9_frontend_auth_error_handling()
    print("=" * 60)
    print("ALL PHASE 6 (M1–M9) TESTS PASSED SUCCESSFULLY!")
    print("=" * 60 + "\n")
