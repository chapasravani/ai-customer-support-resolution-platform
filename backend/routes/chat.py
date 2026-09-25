from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from .. import models
from ..adk_bridge import run_support_workflow
from ..api_schemas import (
    ChatMessageRequest,
    ChatMessageResponse,
    ConversationUpdateRequest,
)
from ..deps import get_current_user


router = APIRouter(prefix="/chat", tags=["chat"])


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
    user: dict = Depends(get_current_user),
):
    user_id = str(user["_id"])

    # -----------------------------------------------------------------------
    # Find existing conversation or create a new one
    # -----------------------------------------------------------------------

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

    else:
        conversation = models.create_conversation(user_id)

    conversation_id = str(conversation["_id"])

    # -----------------------------------------------------------------------
    # Save customer's message
    # -----------------------------------------------------------------------

    models.add_message(
        conversation_id,
        "user",
        payload.message,
    )

    # -----------------------------------------------------------------------
    # Run the existing ADK customer-support workflow
    # -----------------------------------------------------------------------

    workflow_result = await run_support_workflow(
        user_id,
        conversation_id,
        payload.message,
    )

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
    # Save AI response in MongoDB
    # -----------------------------------------------------------------------

    models.add_message(
        conversation_id,
        "assistant",
        response_text,
    )

    # -----------------------------------------------------------------------
    # Create a support case if the ADK workflow requires escalation
    # -----------------------------------------------------------------------

    if _is_escalation_required(escalation):

        # Generate a human-friendly case ID.
        case_id = "CASE-" + uuid4().hex[:8].upper()

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
            models.create_ticket(
                ticket_id=case_id,
                user_id=user_id,
                issue=issue,
                order_id=order_id,
            )

            print(
                f"[ESCALATION] Support case created: "
                f"{case_id}"
            )

        except Exception as exc:
            # Do not break the customer's chat response just because
            # ticket creation failed.
            print(
                f"[ESCALATION ERROR] "
                f"Could not create support case: {exc}"
            )

    # -----------------------------------------------------------------------
    # Return response to frontend
    # -----------------------------------------------------------------------

    return {
        "conversation_id": conversation_id,
        "response": response_text,
    }


# ---------------------------------------------------------------------------
# List conversations
# ---------------------------------------------------------------------------

@router.get("/conversations")
def list_conversations(
    user: dict = Depends(get_current_user),
):
    conversations = models.list_conversations_for_user(
        str(user["_id"])
    )

    return [
        {
            "id": str(c["_id"]),
            "title": c.get("title") or "New conversation",
            "status": c["status"],
            "updated_at": c["updated_at"],
            "message_count": len(
                c.get("messages", [])
            ),
        }
        for c in conversations
    ]


# ---------------------------------------------------------------------------
# Get one conversation
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: dict = Depends(get_current_user),
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
    user: dict = Depends(get_current_user),
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
    user: dict = Depends(get_current_user),
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
