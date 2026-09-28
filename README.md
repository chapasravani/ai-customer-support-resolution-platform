# AI Customer Support & Resolution Platform

An enterprise-ready AI Customer Support & Resolution Platform built on **Google ADK 2.9.1**, **Gemini**, **FastAPI**, **MongoDB** (with local persistent fallback store), and modern responsive Web Frontends.

---

## Architecture Overview

```
                      ┌──────────────────────┐
                      │  Customer / Admin UI │
                      └──────────┬───────────┘
                                 │ HTTP / JSON
                                 ▼
                      ┌──────────────────────┐
                      │    FastAPI Backend   │
                      │  (Auth, Tickets, RAG)│
                      └──────────┬───────────┘
                                 │
           ┌─────────────────────┴─────────────────────┐
           ▼                                           ▼
┌─────────────────────────┐               ┌─────────────────────────┐
│     Google ADK 2.9.1    │               │    Storage Subsystem    │
│   Multi-Agent Workflow  │               │ • MongoDB Cluster       │
│ • State Manager         │               │ • Persistent Fallback   │
│ • Support Manager       │               │   (mongomock + atomic   │
│ • Research Agents       │               │   disk store)           │
│ • Investigation Loop    │               │ • ChromaDB Vector Store │
│ • Resolution & Escalation│              └─────────────────────────┘
└─────────────────────────┘
```

---

## Directory Structure

```
final_customer_support_project/
├── backend/
│   ├── data/                 # Local persistent store (db_store.json)
│   ├── rag/                  # RAG ingestion, ChromaDB vector store, Gemini retriever
│   ├── routes/               # API routes (auth, chat, tickets, documents)
│   ├── adk_bridge.py         # Asynchronous bridge connecting FastAPI to ADK agents
│   ├── db.py                 # MongoDB connection & thread-safe atomic local fallback
│   ├── main.py               # FastAPI entry point & lifespan handler
│   ├── manage_admin.py       # Administrative CLI utility
│   ├── models.py             # Data-access layer for users, conversations, tickets
│   └── requirements.txt      # Backend dependencies (including mongomock, chromadb, etc.)
├── final_customer_support/
│   ├── data/                 # Reference data (orders.json, policies.json, actions.json)
│   ├── tools/                # Business action & escalation tools
│   ├── agent.py              # Root multi-agent ADK workflow
│   └── requirements.txt      # ADK & Gemini dependencies
├── frontend/
│   ├── customer/             # Customer chat UI (HTML/CSS/JS)
│   └── admin/                # Admin management UI
└── pytest.ini                # Root test configuration
```

---

## Quickstart

### 1. Prerequisites & Environment
Ensure Python 3.12 is installed:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r final_customer_support/requirements.txt -r backend/requirements.txt
```

### 2. Configuration
Copy example `.env` files and add your Gemini API key:

```powershell
copy backend\.env.example backend\.env
copy final_customer_support\.env.example final_customer_support\.env
```

Key environment variables:
- `GOOGLE_API_KEY`: Google Gemini API key for ADK agents and RAG embeddings.
- `PROVIDER`: Model provider (default: `gemini`).
- `MODEL`: Primary LLM model (default: `gemini-3.5-flash-lite`).
- `MONGODB_URI`: Connection string (default: `mongodb://localhost:27017` or Atlas URI; falls back automatically to local persistent store if unreachable).
- `MONGODB_DB_NAME`: Database name (default: `customer_support`).
- `JWT_SECRET`: Secret key for signing customer/admin JWT access tokens (minimum 32 characters).
- `JWT_EXPIRES_MINUTES`: Lifetime of JWT tokens (default: `480`).
- `CORS_ORIGINS`: Comma-separated list of allowed origins (e.g. `http://localhost:3000,http://localhost:8000`). Defaults to standard local development ports if unset.

### 3. Run the Backend
```powershell
py -3.12 -m uvicorn backend.main:app --reload --port 8000
```

- API Base: `http://127.0.0.1:8000`
- Interactive OpenAPI Docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`
- Dynamic Model Info: `http://127.0.0.1:8000/system/model-info`

### 4. Run the Frontends
You can open `frontend/customer/index.html` and `frontend/admin/index.html` directly in your browser or serve them with Python:

```powershell
# Customer Frontend (Port 3000)
py -3.12 -m http.server 3000 --directory frontend/customer

# Admin Console (Port 3001)
py -3.12 -m http.server 3001 --directory frontend/admin
```

### 5. Provision Admin Account
Public registration creates customers only. Admin users must be provisioned via the management CLI:

```powershell
py -3.12 -m backend.manage_admin create --email admin@supportai.com --password AdminPassword123! --name "Support Admin"
```

---

## Storage & Reliability Highlights

1. **Persistent Local Fallback Database**:
   - Automatically activates if MongoDB is unreachable within 2.5 seconds.
   - Guarded by re-entrant locks (`threading.RLock`) for thread-safety.
   - Employs atomic disk writes (`tempfile` + `os.replace`) to prevent corrupted data.
   - Automatically re-applies unique indexes (`users.email`, `tickets.ticket_id`, `conversations.conversation_id`) on reload.
2. **Accurate Health Reporting**:
   - `GET /health` distinguishes between live MongoDB connections and the local persistent fallback store.
3. **Dynamic Model Indicators**:
   - Frontends fetch active model branding from `/system/model-info`, gracefully falling back to `● AI Model — unavailable` if offline.
4. **Security & Business Action Guardrails**:
   - Customer/order ownership verification prevents unauthorized cross-customer inquiries or operations.
   - Deterministic policy eligibility and duplicate checks prevent duplicate refunds or cancellations.
   - Sliding-window rate limiting (30 req/min) and message size limits (4,000 chars) protect chat endpoints.
   - Document upload limits (10MB) and RAG untrusted boundary markers protect agent workflows against prompt injection.
   - Feedback persistence endpoint (`/chat/feedback`) saves customer satisfaction ratings to the conversation record.
   - Ticket status update uses `matched_count` semantics so no-op updates succeed without false 404 errors.
   - Conversation list queries exclude message bodies and support limit/skip pagination for optimal performance.

---

## Running Verification Tests

```powershell
# Complete test suite via pytest
py -3.12 -m pytest

# Or run individual phase verification suites:
py -3.12 -m backend.test_phase1                   # Phase 1: Database & Persistent Store Sanity
py -3.12 -m backend.test_phase2                   # Phase 2: Full API, Auth, Documents & Tickets
py -3.12 -m backend.test_phase3_security          # Phase 3: Critical Security (C1, C2, C7)
py -3.12 -m backend.test_phase4_business_actions  # Phase 4: Business Action Safety (C3–C6)
py -3.12 -m backend.test_phase5_reliability       # Phase 5: High Priority Reliability (H1–H6)
py -3.12 -m backend.test_phase6_medium            # Phase 6: Medium Priority Hardening (M1–M9)
py -3.12 -m backend.test_phase7_low               # Phase 7: Low Priority & Maintainability (L1–L6)

# Business Action core unit tests:
py -3.12 -m pytest final_customer_support/tests/test_business_actions.py
```
