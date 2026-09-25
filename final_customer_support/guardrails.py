from google.genai import types
from google.adk.agents.callback_context import CallbackContext


def support_guardrail(callback_context: CallbackContext):
    """Protect resolution/escalation stages from unsupported or unsafe automation."""
    state = callback_context.state
    agent_name = callback_context.agent_name
    investigation = state.get("investigation")

    if agent_name not in {"resolution_agent", "escalation_agent"}:
        return None

    if not investigation:
        state["guardrail_blocked"] = True
        return types.Content(role="model", parts=[types.Part(text="Guardrail blocked this stage: no verified investigation is available.")])

    if isinstance(investigation, dict):
        facts = investigation.get("facts") or []
        policy = investigation.get("applicable_policy")
        if not facts or not policy:
            state["guardrail_blocked"] = True
            return types.Content(role="model", parts=[types.Part(text="Guardrail blocked this stage: investigation evidence or policy is incomplete.")])

    state["guardrail_blocked"] = False
    print(f"[GUARDRAIL] ALLOW -> {agent_name}")
    return None
