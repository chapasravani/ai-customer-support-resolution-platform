# Implementation Progress — AI Customer Support & Resolution Platform

> This file is the single source of truth for implementation status.
> Any Claude session picking this project back up should read this file first,
> then inspect the files listed under "Files changed so far" before writing any code.

---

## STATUS: Phase 2 complete (FastAPI backend + auth + ADK bridge). Existing agent code still untouched.

---

## 1. Current Project — What Actually Exists

Project root (the folder that `adk web` / `adk run` treats as the agent app):
`final_customer_support/`

```
final_customer_support/
├── .env                      # GOOGLE_API_KEY, ADK_MODEL, ENABLE_MCP, ENABLE_OPENAPI
├── .env.example
├── .adk/session.db           # ADK's own local session store (SQLite), created by adk web
├── __init__.py                # `from . import agent`
├── agent.py                   # THE ENTIRE MULTI-AGENT WORKFLOW (root_agent lives here)
├── callbacks.py                # before/after_agent_callback — state defaults + history log
├── guardrails.py               # support_guardrail — blocks resolution/escalation without evidence
├── openapi.yaml                 # OpenAPI spec describing the mock enterprise API
├── openapi_server.py            # Standalone FastAPI app — MOCK ENTERPRISE API, not the app backend
├── mcp_server.py                 # Standalone FastMCP server exposing lookup/create tools over stdio
├── requirements.txt
├── README.md
├── data/
│   ├── customers.json
│   ├── orders.json
│   ├── policies.json
│   ├── support_cases.json        # <- this is today's "tickets" store
│   └── actions.json               # <- log of refund/replacement/cancellation actions
├── schemas/
│   └── support_schemas.py          # Pydantic: InvestigationResult, ResolutionResult, EscalationResult
├── tools/
│   ├── business_actions.py          # create_refund/replacement/cancellation/support_case
│   └── long_running.py                # start_carrier_investigation (LongRunningFunctionTool)
└── tests/
    └── test_business_actions.py
```

### Important finding: there is currently NO FastAPI application backend

`fastapi` and `uvicorn` are in `requirements.txt`, and `openapi_server.py` *is* a FastAPI app —
but it is only the **mock enterprise REST API** that the optional OpenAPI toolset calls into.
There is no existing HTTP layer that wraps the ADK Runner for a real frontend to call.
**This means Phase 2 (FastAPI backend) is new work, not an extension of an existing API file.**

### Workflow (confirmed by reading `agent.py`)

```
root_agent (SequentialAgent "customer_support_system")
 ├── state_agent                     (tool: initialize_support_state)
 ├── support_manager                 (output_key: support_request)
 ├── parallel_research (ParallelAgent)
 │    ├── customer_agent             (tool: get_customer_details)      → output_key: customer_info
 │    ├── order_agent                (tool: get_order_details)         → output_key: order_info
 │    └── knowledge_agent            (tool: get_policy_details)        → output_key: policy_info
 ├── investigation_loop (LoopAgent, max_iterations=2)
 │    ├── investigation_agent        (output_schema: InvestigationResult) → output_key: investigation
 │    └── investigation_review_agent (tool: exit_loop)                 → output_key: investigation_review
 ├── resolution_agent                (output_schema: ResolutionResult)  → output_key: resolution
 │    tools: policy_advisor_tool (AgentTool), create_refund_request, create_replacement_request,
 │           create_cancellation_request, create_support_case
 ├── escalation_agent                (output_schema: EscalationResult)  → output_key: escalation
 └── final_response_agent            (plain text, customer-facing only)
```

Also defined but **not wired into `root_agent`'s sequence** (available as optional specialists):
- `carrier_investigation_agent` (uses the long-running tool)
- `mcp_specialist` (only active if `ENABLE_MCP=true`)
- `openapi_agent` (only active if `ENABLE_OPENAPI=true`)

Every agent has `before_agent_callback` / `after_agent_callback` attached, which:
- seed default session-state keys (`customer_id`, `order_id`, `issue_type`, `workflow_status`, `guardrail_blocked`, `action_status`)
- log a rolling `callback_history` of START/END events per agent
- mark `workflow_status = "completed"` when `final_response_agent` finishes

`support_guardrail` runs before `resolution_agent` and `escalation_agent` and blocks them
(returns a `types.Content` refusal) if there's no `investigation` in state, or if it's missing
`facts`/`applicable_policy`.

### Data & "tickets" today
- All data is local JSON under `data/`.
- `create_support_case` (in `tools/business_actions.py`) writes new cases into `data/support_cases.json` — **this is the existing equivalent of a "ticket."**
- `create_refund_request` / `create_replacement_request` / `create_cancellation_request` write into `data/actions.json`, with idempotency checks (won't double-create for the same order) and a $1000 human-approval threshold for refunds.
- `mcp_server.py` and `openapi_server.py` have their *own* separate `create_support_case_mcp` / `POST /support-cases`, which also write to `data/support_cases.json` — but these paths are inactive unless MCP/OpenAPI are enabled.

### Minor pre-existing inconsistency (not caused by us, not fixing yet)
`tests/test_business_actions.py` imports from `customer_support.tools.business_actions`, but the
actual package folder is `final_customer_support`. This import will fail as-is; it's a pre-existing
issue in the uploaded project, unrelated to our new work. Flagging it, not touching it unless asked.

---

## 2. What Will Be Reused As-Is (no changes)

- `agent.py` — the entire SequentialAgent/ParallelAgent/LoopAgent graph
- `callbacks.py`, `guardrails.py`
- `schemas/support_schemas.py`
- `tools/business_actions.py`, `tools/long_running.py`
- All of `data/*.json`
- `mcp_server.py`, `openapi_server.py`, `openapi.yaml` (remain optional, untouched, still disabled by default)
- `.adk/` session store — ADK Web keeps working exactly as it does today

## 3. What Will Be Added (new files/folders, nothing existing touched)

Planned top-level additions, sitting **next to** `final_customer_support/`, not inside it —
this keeps the existing agent package importable/untouched:

```
project_root/
├── final_customer_support/     # UNCHANGED existing package
├── backend/
│   ├── main.py                  # FastAPI app entrypoint (new)
│   ├── auth.py                   # register/login/JWT (new)
│   ├── db.py                      # MongoDB connection (new)
│   ├── models.py                   # Pydantic request/response + Mongo document shapes (new)
│   ├── adk_bridge.py                 # wraps the existing Runner around root_agent (new)
│   ├── rag/
│   │   ├── ingest.py                  # extract → chunk → embed → store (new)
│   │   └── retriever.py                # retrieve_relevant_documents(query) (new)
│   └── routes/
│       ├── chat.py, tickets.py, documents.py   (new)
├── frontend/
│   ├── customer/  (index.html, chat.html, app.js, style.css)
│   └── admin/     (dashboard.html, documents.html, tickets.html, admin.js)
└── requirements.txt   # extended with new deps (see Phase 1/5 below)
```

## 4. What Will Need Modification (small, later phases — not yet)

- **`agent.py` → `knowledge_agent` only**: its instruction/tools will gain one new tool,
  `retrieve_relevant_documents`, alongside the existing `get_policy_details`. This happens in
  **Phase 6**, not before. Nothing else in `agent.py` changes.
- **`requirements.txt`**: new dependencies appended (Motor/PyMongo, passlib, python-jose,
  python-multipart, pdfplumber/python-docx, chromadb). Nothing removed.

No other existing file requires modification under the current plan.

---

## 5. Decisions That Need Your Confirmation Before Coding Starts

Per your instruction #7, flagging these now rather than deciding silently:

**Decision A — Where does chat history live vs. ADK's own session store?**
ADK already persists its own session/state to `.adk/session.db`. The new `conversations`
collection in MongoDB is a *different* thing: the human-readable chat transcript per user, used
by the customer UI's sidebar. Proposed approach: keep ADK's session store exactly as-is for the
agent's internal reasoning state (per-run), and separately write the user message + final
response into MongoDB after each run completes, in the FastAPI layer — not inside `agent.py`.
→ This means the two stores can technically drift (e.g. if a run partially fails), but keeps the
existing agent code completely untouched. Confirm this is acceptable, or would you rather ADK's
session service be backed by MongoDB directly (bigger change, touches Runner setup)?

**Decision B — Tickets: one system of record, or two?**
`create_support_case` already writes to `data/support_cases.json` today, and that tool is not
being modified. The new admin Ticket UI needs tickets in MongoDB. Proposed approach: after each
ADK run in the FastAPI layer, inspect the `resolution`/`escalation` output keys in the final
state, and if a case/action was created, mirror it into the MongoDB `tickets` collection there —
the JSON file keeps being the thing the agent's tools read/write, MongoDB becomes the
admin-facing view. Confirm you're fine with this mirroring approach (vs. changing
`business_actions.py` to write to MongoDB directly, which would touch existing tool code).

**Decision C — Vector DB choice: Chroma (local, embedded)**
As discussed earlier — no separate server to run, simplest for beginner-friendly maintenance.
Confirm before Phase 5 (can be swapped later; the retriever is planned as an abstraction so this
isn't a locked-in decision).

**Decision D — Embeddings model**
`google-genai==2.23.0` is already a dependency and supports `embed_content`. Proposed: use Gemini's
embedding model rather than adding a separate local embedding library (fewer new dependencies).
Confirm.

---

## 6. Final MongoDB Schemas (for confirmation before Phase 1 code)

```json
// users
{
  "_id": "ObjectId",
  "email": "string, unique",
  "hashed_password": "string",
  "role": "customer | admin",
  "name": "string",
  "created_at": "datetime"
}

// conversations
{
  "_id": "ObjectId",
  "user_id": "ObjectId -> users._id",
  "started_at": "datetime",
  "updated_at": "datetime",
  "status": "active | closed",
  "messages": [
    { "role": "user | assistant", "content": "string", "timestamp": "datetime" }
  ]
}

// tickets
{
  "_id": "ObjectId",
  "ticket_id": "string, human-friendly e.g. CASE-... (mirrors business_actions reference)",
  "conversation_id": "ObjectId -> conversations._id",
  "user_id": "ObjectId -> users._id",
  "order_id": "string",
  "issue": "string",
  "status": "open | investigating | resolved | escalated",
  "priority": "low | medium | high | urgent",
  "resolution_summary": "string, optional",
  "source_reference": "string, the reference from business_actions.py (e.g. CASE-..., REF-...)",
  "created_at": "datetime",
  "updated_at": "datetime"
}

// documents
{
  "_id": "ObjectId",
  "filename": "string",
  "uploaded_by": "ObjectId -> users._id",
  "upload_date": "datetime",
  "status": "processing | indexed | failed",
  "chunk_count": "number",
  "vector_ids": ["string, IDs in Chroma for this doc's chunks"]
}
```
No raw vector embeddings are stored in MongoDB — only metadata and `vector_ids` pointing into Chroma, per your requirement.

---

## 7. Implementation Phases & Status

| Phase | Description | Status |
|---|---|---|
| 0 | Project analysis, this file | ✅ Done |
| 1 | MongoDB connection + collections | ✅ Done |
| 2 | FastAPI backend (new — no existing API to extend) | ✅ Done |
| 3 | Conversation persistence wired to ADK Runner | Not started |
| 4 | Customer UI (HTML/CSS/JS) | Not started |
| 5 | RAG ingestion (Chroma + Gemini embeddings) | Not started |
| 6 | RAG retrieval tool wired into `knowledge_agent` only | Not started |
| 7 | Admin UI | Not started |
| 8 | Final integration + test scenarios 1–5 | Not started |

---

## 8. Known Issues (pre-existing, not introduced by this work)
- `tests/test_business_actions.py` imports a package name (`customer_support`) that doesn't match the actual folder (`final_customer_support`).
- Default `MODEL` fallback in `agent.py` is `"gemini-3.5-flash-lite"` (only used if `.env`'s `ADK_MODEL` is absent; `.env` currently sets a valid model, so this hasn't caused problems yet).

---

## 9. Continuation Prompt (use this verbatim in a new Claude session if needed)

```
Continue implementing the AI Customer Support & Resolution Platform upgrade.
Read IMPLEMENTATION_PROGRESS.md in the project root first, and inspect the files listed under
"Files changed so far" before writing any code. Do not restart the implementation — continue
from the first "Not started" phase in the Phases table. Follow the same constraints as before:
incremental changes, keep the project runnable after each phase, do not rewrite the existing
ADK workflow, confirm any new architectural decision before making it, and update this file
after every completed phase.
```

## 10. Files Changed So Far

**Phase 0:**
- Added: `IMPLEMENTATION_PROGRESS.md` (this file)

**Phase 1 (new folder, nothing existing touched):**
- Added: `backend/__init__.py`
- Added: `backend/db.py` — MongoClient connection, `get_db()`, `ensure_indexes()`, `check_connection()`
- Added: `backend/models.py` — CRUD helper functions for users/conversations/tickets/documents
- Added: `backend/test_phase1.py` — standalone script that creates/reads/updates/deletes one test record in each collection
- Added: `backend/requirements.txt` — `pymongo`, `python-dotenv` (kept separate from `final_customer_support/requirements.txt`, which is untouched)
- Added: `backend/.env.example` — `MONGODB_URI`, `MONGODB_DB_NAME` (separate from `final_customer_support/.env`, which is untouched)

**Verification:** the logic in `test_phase1.py` was run in this session against an in-memory
MongoDB stand-in (not part of the project, not in `requirements.txt`) purely to catch bugs before
handing off. All 6 checks passed: connection, indexes, user create/fetch, conversation create +
2 messages + list, ticket create + status update, document create + status update.
**You still need to run it yourself against a real MongoDB** — see "How to run Phase 1" below.

## 11. How to Run Phase 1 Yourself

```bash
# 1. Install Phase 1 dependencies (in addition to the existing agent's requirements)
pip install -r backend/requirements.txt

# 2. Make sure MongoDB is running - either:
#    a) a local `mongod` on the default port, or
#    b) a MongoDB Atlas free-tier cluster (get the connection string from Atlas)

# 3. Set up your connection settings
cp backend/.env.example backend/.env
# then edit backend/.env if you're not using a plain local MongoDB

# 4. Run the sanity check from the project root (the folder that CONTAINS
#    both final_customer_support/ and backend/)
python -m backend.test_phase1
```

You should see `ALL PHASE 1 CHECKS PASSED.` at the end. The script creates and then deletes its
own test data, so it's safe to run more than once.

If it fails at step 1 with a connection error, MongoDB isn't reachable yet - check `MONGODB_URI`
and that MongoDB is actually running before anything else.

---

## 12. Phase 2 — FastAPI Backend + Auth + ADK Bridge

**New files added (nothing in `final_customer_support/` was touched):**
- `backend/auth.py` — password hashing (bcrypt) and JWT creation/verification. The only file that imports `bcrypt`/`jwt` directly.
- `backend/deps.py` — FastAPI dependencies `get_current_user` and `require_admin`.
- `backend/api_schemas.py` — Pydantic request/response models for the HTTP layer (separate from `models.py`, which is MongoDB CRUD).
- `backend/adk_bridge.py` — wraps the existing `final_customer_support.agent.root_agent` behind one function, `run_support_workflow(user_id, session_id, message)`. Creates one shared `Runner` + `InMemorySessionService` for the process. **Verified by direct import: `root_agent` imports cleanly and constructs into a `Runner` with zero changes to `agent.py`.**
- `backend/routes/auth.py` — `POST /auth/register`, `POST /auth/login`, `GET /auth/me`
- `backend/routes/chat.py` — `POST /chat/message`, `GET /chat/conversations`, `GET /chat/conversations/{id}`
- `backend/routes/tickets.py` — `GET /tickets`, `GET /tickets/{id}`, `PATCH /tickets/{id}` (admin-only)
- `backend/routes/documents.py` — `POST /admin/documents/upload`, `GET /admin/documents`, `DELETE /admin/documents/{id}` (all admin-only)
- `backend/main.py` — the FastAPI app, CORS middleware, `/health`, wires up all routers, creates Mongo indexes on startup
- `backend/test_phase2.py` — sanity check script (see below)
- Updated (additively): `backend/requirements.txt` (added `pyjwt`, `bcrypt`, `python-multipart`, `email-validator`, `httpx`), `backend/.env.example` (added `JWT_SECRET`, `JWT_EXPIRES_MINUTES`)

**Important scope note on `/chat/message`:** it calls the real, existing multi-agent workflow
through `adk_bridge.py` and returns the response. It does **not yet save** the user message or
the assistant's response to MongoDB — that's Phase 3 ("Conversation persistence"). Until Phase 3,
`GET /chat/conversations/{id}` will show an empty `messages` list even after you've chatted,
because nothing is writing to it yet. This was a deliberate incremental split so Phase 2
(auth + routing + the ADK bridge itself) could be fully tested before persistence logic is added
on top of it.

**Important scope note on document upload:** `POST /admin/documents/upload` only records that a
file arrived (`status: "processing"`, metadata saved to MongoDB). Text extraction, chunking,
embedding, and vector storage are Phase 5 (RAG ingestion) — until then, status is never advanced
to `"indexed"` or `"failed"`. This is expected at this phase, not a bug.

**Verification performed in this session:**
1. Imported `final_customer_support.agent.root_agent` unmodified, constructed a real `Runner`
   with it, and created a real ADK session — all succeeded with zero changes to the agent package.
2. Ran the full `test_phase2.py` script against an in-memory MongoDB stand-in (not part of your
   project) to catch bugs before handing off: health check, register, login, `/auth/me`,
   admin-only 403 enforcement, document upload/list/delete, ticket create/list/patch with
   correct 403 for non-admins — all passed.
3. Did **not** call `/chat/message` with a real message in this session, to avoid spending your
   Gemini API quota without asking first.

**You still need to run it yourself** against your real MongoDB Atlas (and, optionally, a real
chat message):

```bash
# From the project root (contains both final_customer_support/ and backend/)
pip install -r backend/requirements.txt

# Uses backend/.env (already set up from Phase 1) - add JWT_SECRET, e.g.:
python -c "import secrets; print(secrets.token_hex(32))"
# paste the result into backend/.env as JWT_SECRET=...

# Run the Phase 2 checks (auth, tickets, documents - no live Gemini call)
python -m backend.test_phase2

# Optional: also send one real message through the full ADK workflow
# (this WILL use your Gemini API quota)
RUN_LIVE_CHAT_TEST=1 python -m backend.test_phase2
```

You should see `ALL PHASE 2 CHECKS PASSED.` If you run the live chat test, you'll also see the
agent's actual response printed - that's your confirmation the FastAPI → ADK Runner → your
existing multi-agent workflow path works end-to-end.

If you want to try it interactively instead of via the test script:
```bash
uvicorn backend.main:app --reload
# then open http://127.0.0.1:8000/docs for interactive Swagger UI
```
