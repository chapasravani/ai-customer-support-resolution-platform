import time
import re
from collections import defaultdict
from threading import Lock
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from backend.app.domains import models
from backend.app.workflows.adk_bridge import run_support_workflow
from backend.app.api.schemas import (
    ChatMessageRequest,
    ConversationUpdateRequest,
    FeedbackRequest,
)
from backend.app.core.deps import require_customer


router = APIRouter(prefix="/chat", tags=["chat"])

_rate_limit_lock = Lock()
_user_request_timestamps: dict[str, list[float]] = defaultdict(list)
CHAT_RATE_LIMIT_REQUESTS = 30
CHAT_RATE_LIMIT_WINDOW_SECONDS = 60


def reset_chat_rate_limits() -> None:
    """Reset rate limiting data (useful for test isolation)."""
    with _rate_limit_lock:
        _user_request_timestamps.clear()


def _check_rate_limit(
    user_id: str,
    limit: int = CHAT_RATE_LIMIT_REQUESTS,
    window: int = CHAT_RATE_LIMIT_WINDOW_SECONDS,
) -> None:
    now = time.time()
    cutoff = now - window
    with _rate_limit_lock:
        timestamps = _user_request_timestamps[user_id]
        valid_timestamps = [t for t in timestamps if t > cutoff]
        if len(valid_timestamps) >= limit:
            _user_request_timestamps[user_id] = valid_timestamps
            retry_after = int(valid_timestamps[0] + window - now) + 1
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded. Please wait a moment before sending another message.",
                headers={"Retry-After": str(max(1, retry_after))},
            )
        valid_timestamps.append(now)
        _user_request_timestamps[user_id] = valid_timestamps


# ---------------------------------------------------------------------------
# Helper: determine whether the ADK workflow requires human escalation
# ---------------------------------------------------------------------------

def _is_escalation_required(escalation: dict) -> bool:
    """
    Check the escalation information returned by the ADK workflow.

    The ADK escalation agent is expected to produce a field such as:
        should_escalate: true / false
    """

    if not isinstance(escalation, dict):
        return False

    value = escalation.get("should_escalate", False)

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.lower().strip() in {
            "true",
            "yes",
            "1",
        }

    return bool(value)


# ---------------------------------------------------------------------------
# Helper: get the escalation reason
# ---------------------------------------------------------------------------

def _get_escalation_reason(escalation: dict) -> str:
    """
    Extract a human-readable reason from the ADK escalation result.
    """

    if not isinstance(escalation, dict):
        return ""

    return (
        escalation.get("reason")
        or escalation.get("escalation_reason")
        or escalation.get("message")
        or ""
    )


# ---------------------------------------------------------------------------
# Send customer message
# ---------------------------------------------------------------------------

@router.post("/message")
async def send_message(
    payload: ChatMessageRequest,
    user: dict = Depends(require_customer),
):
    user_id = str(user["_id"])
    _check_rate_limit(user_id)

    # -----------------------------------------------------------------------
    # Find existing conversation or create a new one
    # -----------------------------------------------------------------------

    conversation = None
    if payload.conversation_id:
        conversation = models.get_conversation(payload.conversation_id)

        if (
            not conversation
            or str(conversation["user_id"]) != user_id
        ):
            raise HTTPException(
                404,
                "Conversation not found.",
            )

    request_record = None
    request_state = ""
    if payload.request_id:
        request_state, request_record = models.claim_chat_request(
            user_id, payload.request_id, payload.conversation_id or ""
        )
        if request_state == "done":
            return {
                "conversation_id": request_record.get("conversation_id", ""),
                "response": request_record.get("response", ""),
                "deduplicated": True,
            }
        if request_state == "in_progress":
            raise HTTPException(status_code=409, detail="request in progress")

    conversation_id = payload.conversation_id or ""
    user_message = None
    try:
        if conversation is None and request_record and request_record.get("conversation_id"):
            conversation = models.get_conversation(request_record["conversation_id"])
        if conversation is None:
            conversation = models.create_conversation(user_id)
        conversation_id = str(conversation["_id"])
        if payload.request_id:
            models.update_chat_request(user_id, payload.request_id, "in_progress", conversation_id=conversation_id)

        # -----------------------------------------------------------------------
        # Save customer's message
        # -----------------------------------------------------------------------

        user_message = None
        if payload.request_id and request_state == "retry":
            user_message = next(
                (m for m in conversation.get("messages", []) if m.get("request_id") == payload.request_id),
                None,
            )
        if user_message is None:
            user_message = models.add_message(
                conversation_id,
                "user",
                payload.message,
                request_id=payload.request_id or "",
            )

        # -----------------------------------------------------------------------
        # Run the existing ADK customer-support workflow
        # -----------------------------------------------------------------------

        customer_id = models.get_customer_id_for_user(user)
        user_email = user.get("email", "")
        user_role = user.get("role", "customer")

        try:
            workflow_result = await run_support_workflow(
                user_id=user_id,
                session_id=conversation_id,
                message=payload.message,
                customer_id=customer_id,
                user_email=user_email,
                user_role=user_role,
            )
        except Exception as exc:
            if user_message:
                models.set_message_failed(conversation_id, user_message["id"], True)
            if payload.request_id:
                models.update_chat_request(user_id, payload.request_id, "failed", conversation_id=conversation_id)
            raise HTTPException(status_code=503, detail="The support workflow failed. Please retry this request.") from exc

        # -----------------------------------------------------------------------
        # Extract the final customer-facing response
        # -----------------------------------------------------------------------

        response_text = workflow_result.get(
            "response",
            "I wasn't able to generate a response. Please try again.",
        )

        # -----------------------------------------------------------------------
        # Extract workflow information
        #
        # These values were produced by the ADK agents and stored in
        # the ADK session state.
        # -----------------------------------------------------------------------

        escalation = workflow_result.get(
            "escalation",
            {},
        )

        investigation = workflow_result.get(
            "investigation",
            {},
        )

        resolution = workflow_result.get(
            "resolution",
            {},
        )

        order_id = workflow_result.get(
            "order_id",
            "",
        )

        issue_type = workflow_result.get(
            "issue_type",
            "",
        )

        # -----------------------------------------------------------------------
        # H5: Do not store a failed workflow as if it were a successful assistant response
        # -----------------------------------------------------------------------

        is_workflow_success = workflow_result.get("success", True)
        if not is_workflow_success:
            if user_message:
                models.set_message_failed(conversation_id, user_message["id"], True)
            if payload.request_id:
                models.update_chat_request(user_id, payload.request_id, "failed", conversation_id=conversation_id)
            return {
                "conversation_id": conversation_id,
                "response": response_text,
                "error": workflow_result.get("error_type", "workflow_failure"),
                "error_type": workflow_result.get("error_type", "workflow_failure"),
            }

        # -----------------------------------------------------------------------
        # Create or update support case if the ADK workflow requires escalation
        # -----------------------------------------------------------------------

        if _is_escalation_required(escalation):

            # Get the reason provided by the escalation agent.
            escalation_reason = _get_escalation_reason(
                escalation
            )

            # Use the most useful issue description available.
            issue = (
                escalation_reason
                or issue_type
                or payload.message
            )

            try:
                # The Mongo-backed route owns ticket identity and creation.
                ticket = models.find_or_create_open_ticket(
                    ticket_id="CASE-" + uuid4().hex[:12].upper(),
                    user_id=user_id,
                    issue=issue,
                    order_id=order_id,
                    conversation_id=conversation_id,
                )
                case_id = ticket["ticket_id"]
                if not models.update_ticket_issue(case_id, issue, order_id=order_id):
                    raise RuntimeError("Ticket disappeared during update")
                response_text = re.sub(r"\bCASE-[A-Z0-9-]+\b", "your support request", response_text, flags=re.IGNORECASE)
                response_text = f"{response_text.rstrip()} Your reference is {case_id}."
            except Exception:
                if user_message:
                    models.set_message_failed(conversation_id, user_message["id"], True)
                if payload.request_id:
                    models.update_chat_request(user_id, payload.request_id, "failed", conversation_id=conversation_id)
                return {
                    "conversation_id": conversation_id,
                    "response": "Your request needs specialist assistance, but we encountered an issue creating the support ticket. Please try again.",
                    "error": True,
                    "error_type": "ticket_creation_failed",
                }

        # -----------------------------------------------------------------------
        # Save valid AI response in MongoDB
        # -----------------------------------------------------------------------

        models.add_message(
            conversation_id,
            "assistant",
            response_text,
        )

        if payload.request_id:
            if user_message:
                models.set_message_failed(conversation_id, user_message["id"], False)
            models.update_chat_request(user_id, payload.request_id, "done", response_text, conversation_id)

        # -----------------------------------------------------------------------
        # Return response to frontend
        # -----------------------------------------------------------------------

        return {
            "conversation_id": conversation_id,
            "response": response_text,
        }



    except Exception:
        if payload.request_id:
            if user_message and conversation_id:
                models.set_message_failed(conversation_id, user_message["id"], True)
            models.update_chat_request(user_id, payload.request_id, "failed", conversation_id=conversation_id)
        raise

# ---------------------------------------------------------------------------
# List conversations
# ---------------------------------------------------------------------------

@router.get("/conversations")
def list_conversations(
    limit: int = 20,
    skip: int = 0,
    user: dict = Depends(require_customer),
):
    limit = max(1, min(limit, 100))
    skip = max(0, skip)
    conversations = models.list_conversations_for_user(
        str(user["_id"]),
        limit=limit,
        skip=skip,
        include_messages=False,
    )

    return [
        {
            "id": str(c["_id"]),
            "title": c.get("title") or "New conversation",
            "status": c["status"],
            "updated_at": c["updated_at"],
            "message_count": c.get(
                "message_count",
                len(c.get("messages", [])),
            ),
        }
        for c in conversations
    ]


# ---------------------------------------------------------------------------
# Submit customer feedback (L4)
# ---------------------------------------------------------------------------

@router.post("/feedback")
def submit_feedback(
    payload: FeedbackRequest,
    user: dict = Depends(require_customer),
):
    saved = models.save_feedback(
        conversation_id=payload.conversation_id,
        user_id=str(user["_id"]),
        rating=payload.rating,
        message_index=payload.message_index,
    )

    if not saved:
        raise HTTPException(
            404,
            "Conversation not found or access denied.",
        )

    return {
        "status": "success",
        "message": "Feedback recorded successfully.",
    }


# ---------------------------------------------------------------------------
# Get one conversation
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: dict = Depends(require_customer),
):
    conversation = models.get_conversation(
        conversation_id
    )

    if (
        not conversation
        or str(conversation["user_id"])
        != str(user["_id"])
    ):
        raise HTTPException(
            404,
            "Conversation not found.",
        )

    return {
        "id": str(conversation["_id"]),
        "title": conversation.get("title")
        or "New conversation",
        "status": conversation["status"],
        "messages": conversation.get(
            "messages",
            [],
        ),
    }


# ---------------------------------------------------------------------------
# Rename conversation
# ---------------------------------------------------------------------------

@router.patch("/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: str,
    payload: ConversationUpdateRequest,
    user: dict = Depends(require_customer),
):
    conversation = models.get_conversation(
        conversation_id
    )

    if (
        not conversation
        or str(conversation["user_id"])
        != str(user["_id"])
    ):
        raise HTTPException(
            404,
            "Conversation not found.",
        )

    title = " ".join(
        payload.title.split()
    ).strip()

    if not title:
        raise HTTPException(
            400,
            "Conversation title cannot be empty.",
        )

    if not models.rename_conversation(
        conversation_id,
        title,
    ):
        raise HTTPException(
            404,
            "Conversation not found.",
        )

    return {
        "id": conversation_id,
        "title": title[:80],
    }


# ---------------------------------------------------------------------------
# Delete conversation
# ---------------------------------------------------------------------------

@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    user: dict = Depends(require_customer),
):
    conversation = models.get_conversation(
        conversation_id
    )

    if (
        not conversation
        or str(conversation["user_id"])
        != str(user["_id"])
    ):
        raise HTTPException(
            404,
            "Conversation not found.",
        )

    if not models.delete_conversation(
        conversation_id
    ):
        raise HTTPException(
            404,
            "Conversation not found.",
        )
    return {
        "message": "Conversation deleted successfully.",
        "id": conversation_id,
    }
