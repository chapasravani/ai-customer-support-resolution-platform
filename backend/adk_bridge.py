"""
Wraps the EXISTING ADK multi-agent workflow
(final_customer_support.agent.root_agent) behind one simple async
function: run_support_workflow(...).

This file does not change the agent graph. It only:
- creates the ADK Runner
- manages the ADK session
- runs one customer message
- collects the final response
- collects investigation / resolution / escalation state
- handles temporary API failures gracefully
"""

import asyncio
import os

from pathlib import Path
from dotenv import load_dotenv

# Load backend/.env reliably
_backend_env = Path(__file__).resolve().parent / ".env"
if _backend_env.exists():
    load_dotenv(_backend_env)

# Also ensure final_customer_support/.env is loaded as fallback
_fcs_env = Path(__file__).resolve().parent.parent / "final_customer_support" / ".env"
if _fcs_env.exists():
    load_dotenv(_fcs_env)

provider = os.getenv("PROVIDER", "gemini").lower()
configured_api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("API_KEY")

if configured_api_key and provider == "gemini":
    os.environ["GOOGLE_API_KEY"] = configured_api_key


from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from final_customer_support.agent import root_agent, fallback_root_agent


APP_NAME = "customer_support_system"


# ---------------------------------------------------------------------------
# ADK session + runners (Primary & Fallback)
# ---------------------------------------------------------------------------

_session_service = InMemorySessionService()

_primary_runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    session_service=_session_service,
)

_fallback_runner = Runner(
    app_name=APP_NAME,
    agent=fallback_root_agent,
    session_service=_session_service,
) if fallback_root_agent is not root_agent else _primary_runner


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------

async def _get_or_create_session(
    user_id: str,
    session_id: str,
    initial_state: dict = None,
):
    session = await _session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    if session is None:
        session = await _session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state=initial_state or {},
        )
        # H6: Hydrate session from existing Mongo conversation history across restarts
        try:
            from . import models
            convo = models.get_conversation(session_id)
            if convo and convo.get("messages"):
                from google.adk.events.event import Event
                past_turns = [m for m in convo["messages"][:-1] if not m.get("failed")]
                for msg in past_turns:
                    role = msg.get("role", "user")
                    text = msg.get("content", "")
                    if text:
                        adk_role = "user" if role == "user" else "model"
                        evt = Event(
                            author=role,
                            content=types.Content(
                                role=adk_role,
                                parts=[types.Part(text=text)],
                            ),
                        )
                        await _session_service.append_event(session, evt)
        except Exception:
            await _session_service.delete_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
            raise
    elif initial_state:
        from google.adk.events.event import Event, EventActions
        changed_state = {
            key: value for key, value in initial_state.items()
            if (session.state or {}).get(key) != value
        }
        if changed_state:
            evt = Event(actions=EventActions(state_delta=changed_state))
            await _session_service.append_event(session, evt)

    # Re-fetch session to verify persisted state
    session = await _session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    if initial_state and any(session.state.get(key) != value for key, value in initial_state.items()):
        raise RuntimeError("Authenticated session state did not persist")
    return session


# ---------------------------------------------------------------------------
# Main workflow
# ---------------------------------------------------------------------------

async def run_support_workflow(
    user_id: str,
    session_id: str,
    message: str,
    customer_id: str = None,
    user_email: str = None,
    user_role: str = "customer",
) -> dict:
    """
    Run one customer message through the existing ADK workflow.

    Returns:
        {
            "response": final customer-facing response,
            "escalation": escalation information,
            "investigation": investigation information,
            "resolution": resolution information,
            "order_id": order ID,
            "issue_type": issue type
        }

    Temporary API failures are converted into friendly responses
    instead of allowing FastAPI to return an unhandled 500 error.
    """

    # -----------------------------------------------------------------------
    # Make sure the ADK session exists with authenticated customer context
    # -----------------------------------------------------------------------

    auth_state = {}
    if customer_id:
        auth_state["authenticated_customer_id"] = customer_id
    if user_email:
        auth_state["authenticated_user_email"] = user_email
    if user_role:
        auth_state["authenticated_user_role"] = user_role

    try:
        session = await _get_or_create_session(
            user_id,
            session_id,
            initial_state=auth_state,
        )
    except Exception:
        return {
            "response": "Your conversation history is temporarily unavailable. Please try again.",
            "success": False,
            "error_type": "history_unavailable",
            "escalation": {}, "investigation": {}, "resolution": {}, "order_id": "", "issue_type": "",
        }

    # -----------------------------------------------------------------------
    # Convert the customer's message into an ADK Content object
    # -----------------------------------------------------------------------

    content = types.Content(
        role="user",
        parts=[
            types.Part(text=message)
        ],
    )

    final_text = ""
    action_started = False
    runners_to_try = [("primary", _primary_runner)]
    if _fallback_runner is not _primary_runner:
        runners_to_try.append(("fallback", _fallback_runner))

    for runner_name, runner in runners_to_try:
        max_retries = 1
        for attempt in range(max_retries + 1):
            try:
                # ---------------------------------------------------------------
                # Run the EXISTING ADK multi-agent workflow
                # ---------------------------------------------------------------
                async for event in runner.run_async(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=content,
                ):
                    author = str(getattr(event, "author", "") or getattr(event, "node_name", ""))
                    if "business_action_agent" in author.lower():
                        action_started = True
                    for part in getattr(getattr(event, "content", None), "parts", []) or []:
                        call = getattr(part, "function_call", None)
                        if call and getattr(call, "name", "") in {
                            "create_refund_request", "create_replacement_request",
                            "create_cancellation_request", "create_support_case",
                        }:
                            action_started = True
                    # Capture response from agents
                    if event.content and event.content.parts:
                        text = "".join(
                            part.text or ""
                            for part in event.content.parts
                        ).strip()
                        if text:
                            author = (
                                getattr(event, "author", None)
                                or getattr(event, "node_name", "")
                                or ""
                            )
                            if "final_response" in str(author).lower():
                                final_text = text
                            elif not final_text:
                                final_text = text
                            elif event.is_final_response():
                                final_text = text

                if final_text:
                    break
                if action_started:
                    return {
                        "response": "Your request may have started an action, but the workflow stopped before it could confirm the result. Please contact support before retrying.",
                        "success": False,
                        "error_type": "partial_after_action",
                        "escalation": {}, "investigation": {}, "resolution": {}, "order_id": "", "issue_type": "",
                    }

            except Exception as exc:
                error_text = str(exc)
                is_transient = (
                    "429" in error_text
                    or "RESOURCE_EXHAUSTED" in error_text
                    or "503" in error_text
                    or "UNAVAILABLE" in error_text
                    or "timeout" in error_text.lower()
                    or "rate limit" in error_text.lower()
                    or "quota" in error_text.lower()
                )

                if action_started:
                    return {
                        "response": "Your request may have started an action, but the workflow stopped before it could confirm the result. Please contact support before retrying.",
                        "success": False,
                        "error_type": "partial_after_action",
                        "escalation": {}, "investigation": {}, "resolution": {}, "order_id": "", "issue_type": "",
                    }

                if is_transient:
                    if attempt < max_retries:
                        backoff = 2.0
                        print(f"[RETRY] {runner_name} LLM limit ({type(exc).__name__}). Retrying in {backoff}s...")
                        await asyncio.sleep(backoff)
                        continue
                    elif runner_name == "primary" and len(runners_to_try) > 1:
                        print(f"[FALLBACK] Switching from primary to fallback runner due to: {type(exc).__name__}: {error_text[:100]}")
                        break

                print("\n" + "=" * 70)
                print(f"[ADK ERROR] ({runner_name})")
                print(f"{type(exc).__name__}: {error_text}")
                print("=" * 70)
                # If primary failed with non-transient, try fallback before giving up
                if runner_name == "primary" and len(runners_to_try) > 1:
                    print("[FALLBACK] Attempting fallback runner after non-transient error on primary...")
                    break

                # Rate limit / quota error
                if (
                    "429" in error_text
                    or "RESOURCE_EXHAUSTED" in error_text
                    or "rate limit" in error_text.lower()
                    or "quota" in error_text.lower()
                ):
                    return {
                        "response": (
                            "I'm temporarily receiving a high volume of requests. "
                            "Please wait a brief moment and try again."
                        ),
                        "success": False,
                        "error_type": "rate_limit",
                        "escalation": {},
                        "investigation": {},
                        "resolution": {},
                        "order_id": "",
                        "issue_type": "",
                    }

                # Temporary service availability error
                if (
                    "503" in error_text
                    or "UNAVAILABLE" in error_text
                    or "high demand" in error_text.lower()
                    or "temporarily unavailable" in error_text.lower()
                ):
                    return {
                        "response": (
                            "The AI service is temporarily busy. "
                            "Please wait a moment and try again."
                        ),
                        "success": False,
                        "error_type": "service_unavailable",
                        "escalation": {},
                        "investigation": {},
                        "resolution": {},
                        "order_id": "",
                        "issue_type": "",
                    }

                # Generic workflow failure
                return {
                    "response": (
                        "I'm currently unable to complete your request. "
                        "Please try again in a moment."
                    ),
                    "success": False,
                    "error_type": "workflow_failure",
                    "escalation": {},
                    "investigation": {},
                    "resolution": {},
                    "order_id": "",
                    "issue_type": "",
                }

        if final_text:
            break

    # -----------------------------------------------------------------------
    # IMPORTANT:
    # After the ADK workflow finishes, read the state produced by the agents.
    # -----------------------------------------------------------------------

    session = await _session_service.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    state = dict(session.state or {}) if session else {}

    # If state captured final_response directly, prioritize it
    if state.get("final_response") and isinstance(state["final_response"], str) and len(state["final_response"]) > 10:
        final_text = state["final_response"]

    # -----------------------------------------------------------------------
    # Extract information produced by the ADK workflow
    # -----------------------------------------------------------------------

    escalation = state.get("escalation", {})
    investigation = state.get("investigation", {})
    resolution = state.get("resolution", {})

    order_id = state.get("order_id", "")
    issue_type = state.get("issue_type", "")

    # -----------------------------------------------------------------------
    # Return EVERYTHING needed by the FastAPI backend
    # -----------------------------------------------------------------------

    if not final_text:
        return {
            "response": "I wasn't able to generate a response. Please try again.",
            "success": False,
            "error_type": "empty_response",
            "escalation": {}, "investigation": {}, "resolution": {}, "order_id": "", "issue_type": "",
        }

    return {
        "response": final_text,
        "success": True,
        "escalation": escalation,
        "investigation": investigation,
        "resolution": resolution,
        "order_id": order_id,
        "issue_type": issue_type,
    }
