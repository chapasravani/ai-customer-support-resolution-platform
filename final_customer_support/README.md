# AI Customer Support & Resolution Platform

A multi-agent customer-support system built with **Google ADK 2.9.1 + Gemini**.

## Architecture

Customer → Support Manager → parallel Customer/Order/Knowledge research → Investigation Loop → Resolution → Business Action or Escalation → Final Response.


╔══════════════════════════════════════════════════════════════════════╗
║            AI CUSTOMER SUPPORT & RESOLUTION PLATFORM                 ║
║                     Google ADK 2.9.1 + Gemini                        ║
╚══════════════════════════════════════════════════════════════════════╝

                              CUSTOMER
                                 │
                                 │ Customer Query
                                 ▼
                    ┌─────────────────────────┐
                    │      STATE MANAGER      │
                    │                         │
                    │ • Initialize State      │
                    │ • Read Customer Query   │
                    │ • Extract Order ID      │
                    │ • Identify Issue Type   │
                    │ • Initialize Context    │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │     SUPPORT MANAGER     │
                    │                         │
                    │ • Understand Query      │
                    │ • Prepare Case          │
                    │ • Create Investigation  │
                    │   Brief                 │
                    └────────────┬────────────┘
                                 │
                                 ▼
              ┌─────────────────────────────────────┐
              │        PARALLEL RESEARCH            │
              │          ParallelAgent              │
              └───────────────┬─────────────────────┘
                              │
             ┌────────────────┼────────────────┐
             │                │                │
             ▼                ▼                ▼
    ┌────────────────┐ ┌────────────────┐ ┌────────────────┐
    │ CUSTOMER AGENT │ │   ORDER AGENT  │ │ KNOWLEDGE AGENT│
    │                │ │                │ │                │
    │ • Customer     │ │ • Order Status │ │ • Policies     │
    │   Profile      │ │ • Order Items  │ │ • FAQs         │
    │ • History      │ │ • Delivery     │ │ • Procedures   │
    │ • Eligibility  │ │ • Payment      │ │ • Guidelines   │
    └───────┬────────┘ └───────┬────────┘ └───────┬────────┘
            │                  │                  │
            └──────────────────┼──────────────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │  INVESTIGATION LOOP    │
                  │      LoopAgent         │
                  │                        │
                  │  Investigation         │
                  │       ↓                │
                  │  Review / Validate     │
                  │       ↓                │
                  │  More info needed?     │
                  └───────────┬────────────┘
                              │
                              ▼
                  ┌────────────────────────┐
                  │    RESOLUTION AGENT    │
                  │                        │
                  │ • Analyze Evidence     │
                  │ • Apply Policy         │
                  │ • Decide Resolution    │
                  │ • Select Action        │
                  └────────────┬───────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                  ▼                         ▼
       ┌─────────────────────┐   ┌─────────────────────┐
       │   BUSINESS ACTION   │   │  HUMAN ESCALATION   │
       │                     │   │                     │
       │ • Refund            │   │ • Create Case       │
       │ • Replacement       │   │ • Human Handoff     │
       │ • Cancellation      │   │ • Approval Required │
       │ • Support Case      │   │ • High-value Case   │
       └──────────┬──────────┘   └──────────┬──────────┘
                  │                         │
                  └────────────┬────────────┘
                               │
                               ▼
                  ┌────────────────────────┐
                  │   FINAL RESPONSE AGENT │
                  │                        │
                  │ • Summarize Resolution │
                  │ • Explain Action       │
                  │ • Customer-friendly    │
                  │   Response             │
                  └────────────┬───────────┘
                               │
                               ▼
                         ┌───────────┐
                         │ CUSTOMER  │
                         └───────────┘

## ADK concepts demonstrated

- LlmAgent / Agent
- SequentialAgent
- ParallelAgent
- LoopAgent
- Function tools
- Agent-as-a-Tool
- Pydantic structured output
- Session state and shared context
- Callbacks
- Guardrails
- MCP with `McpToolset`
- OpenAPI with `OpenAPIToolset`
- `LongRunningFunctionTool`
- Human escalation / case handoff

## Setup & Installation

1. Create and activate a Python 3.12 virtual environment:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies for both the multi-agent system and the backend:

```powershell
pip install -r final_customer_support/requirements.txt -r backend/requirements.txt
```

> **Note on mongomock**: `mongomock==4.3.0` is included in `backend/requirements.txt`. It powers the file-backed persistent local fallback database when a live MongoDB instance is not connected.

3. Configure environment variables:

```powershell
copy backend\.env.example backend\.env
copy final_customer_support\.env.example final_customer_support\.env
```

Ensure your `GOOGLE_API_KEY` is placed in `backend/.env` (and `final_customer_support/.env` if testing agents directly). Never commit `.env` files.

---

## Storage & Reliability Architecture

### Persistent Local Fallback Database
- **Automatic Fallback**: If a connection to `MONGODB_URI` cannot be established within 2.5s, the system automatically falls back to a file-backed persistent local database (`backend/data/db_store.json`) powered by `mongomock`.
- **Atomic Writes**: Writes to `db_store.json` use a safe `tempfile` + `os.replace` strategy to guarantee disk integrity without partial write corruption.
- **Thread Safety**: All reads, writes, and sync operations in `backend/db.py` are guarded by a re-entrant lock (`threading.RLock()`).
- **Index Preservation**: Collection drops during disk reload automatically re-apply unique indexes on `users.email` and `tickets.ticket_id`.

---

## System Endpoints

### 1. Storage Health (`GET /health`)
Clearly distinguishes between live MongoDB connections and the local persistent fallback store:

```json
{
  "status": "ok",
  "storage_type": "local_persistent_fallback",
  "mongodb_connected": false,
  "persistent_fallback_active": true,
  "details": "Using file-backed persistent local database (mongomock)."
}
```

When connected to live MongoDB:
```json
{
  "status": "ok",
  "storage_type": "mongodb",
  "mongodb_connected": true,
  "persistent_fallback_active": false,
  "details": "Connected to remote MongoDB."
}
```

### 2. Active Model Info (`GET /system/model-info`)
Provides dynamic AI model branding and metadata for frontend badges:

```json
{
  "provider": "gemini",
  "provider_display": "Google Gemini",
  "model": "gemini-3.5-flash-lite",
  "fallback_model": "gemini-3.1-flash-lite",
  "display_name": "Google Gemini — gemini-3.5-flash-lite"
}
```
If `/system/model-info` is unreachable, the customer UI model badge defaults to a neutral status: `● AI Model — unavailable`.

---

## Complete System Startup Instructions

### Step 1: Start the Backend API
From the repository root (`final_customer_support_project`):

```powershell
py -3.12 -m uvicorn backend.main:app --reload --port 8000
```

The API will be available at `http://127.0.0.1:8000` (docs at `http://127.0.0.1:8000/docs`).

### Step 2: Open Customer Frontend
Open `frontend/customer/index.html` in your web browser, or serve with a local server:

```powershell
py -3.12 -m http.server 3000 --directory frontend/customer
```
Navigate to `http://127.0.0.1:3000`.

### Step 3: Open Admin Console
Open `frontend/admin/index.html` in your web browser, or serve with a local server:

```powershell
py -3.12 -m http.server 3001 --directory frontend/admin
```
Navigate to `http://127.0.0.1:3001`.

### Step 4: Provision Admin Account
Use the admin management CLI:

```powershell
py -3.12 -m backend.manage_admin create --email admin@supportai.com --password AdminPassword123! --name "Support Admin"
```

---

## Running Verification Tests

```powershell
# Run all tests using pytest
py -3.12 -m pytest

# Or run individual phase test suites:
py -3.12 -m backend.test_phase1                   # Phase 1: Database & Fallback Store Sanity
py -3.12 -m backend.test_phase2                   # Phase 2: Full API, Auth, Documents & Tickets
py -3.12 -m backend.test_phase3_security          # Phase 3: Critical Security (C1, C2, C7)
py -3.12 -m backend.test_phase4_business_actions  # Phase 4: Business Action Safety (C3–C6)
py -3.12 -m backend.test_phase5_reliability       # Phase 5: High Priority Reliability (H1–H6)
py -3.12 -m backend.test_phase6_medium            # Phase 6: Medium Priority Hardening (M1–M9)
py -3.12 -m backend.test_phase7_low               # Phase 7: Low Priority & Maintainability (L1–L6)

# Business Action core unit tests:
py -3.12 -m pytest final_customer_support/tests/test_business_actions.py
```

## Example Scenarios

1. `My order ORD123 is delayed. What can I do?`
2. `My order ORD124 arrived damaged and I want a replacement.`
3. `My order ORD124 arrived damaged and I want a refund.`
4. `Please cancel ORD125.`
5. `My order ORD125 arrived damaged. I want a refund.`
6. `I have a problem with my order.`

## Safety Model

Business actions validate order state and policy, are idempotent where appropriate, and high-value refunds are routed for human approval.
