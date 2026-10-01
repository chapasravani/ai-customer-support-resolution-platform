# API

Base URL in local development: `http://127.0.0.1:8000`. Interactive OpenAPI docs: `/docs`.
Route handlers live in `backend/app/api/routes/`; request and response models in `backend/app/api/schemas.py`.

## Public and customer routes

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Storage mode and RAG status (`rag: unavailable` on outage) |
| `GET /system/model-info` | none | Active model names |
| `POST /auth/register` | none | Create a customer account. Always returns the same 202 body |
| `POST /auth/login` | none | Returns a JWT. Rate limited per IP and per IP + email (429 + `Retry-After`) |
| `GET /auth/me` | bearer | Current user |
| `POST /chat/message` | customer | Send a message. Send a client-generated `request_id`; retries must reuse it |
| `GET /chat/conversations` | customer | List own conversations |
| `GET/PATCH/DELETE /chat/conversations/{conversation_id}` | customer | Read, rename, delete own conversation |
| `POST /chat/feedback` | customer | Thumbs up/down on an assistant turn |

## Admin routes

| Method and path | Purpose |
|---|---|
| `GET /tickets` | List or filter tickets |
| `GET /tickets/{ticket_id}` | Read one ticket |
| `PATCH /tickets/{ticket_id}` | Update status and resolution |
| `GET /admin/actions` | List refund / replacement / cancellation requests, optional `status` filter |
| `PATCH /admin/actions/{reference}` | Approve or reject a pending action (`status`, `reason`) |
| `GET /admin/documents` | List policy documents |
| `POST /admin/documents/upload` | Upload a policy document (optional `replace_document_id`) |
| `DELETE /admin/documents/{document_id}` | Delete a document and exactly its vectors |

## Chat response contract

Success: `{conversation_id, reply, escalation?, deduplicated?}`.
Failure: `{error: true, error_type, ...}` with `error_type` one of `partial_after_action`, `empty_response`, `history_unavailable`, `ticket_creation_failed`, or a provider error. Failed turns are not saved as assistant answers.

A repeated `request_id` returns the stored answer; a concurrent duplicate gets `409`.
