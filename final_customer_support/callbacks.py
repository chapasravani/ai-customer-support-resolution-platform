from google.adk.agents.callback_context import CallbackContext


def before_agent_callback(callback_context: CallbackContext):
    state = callback_context.state
    defaults = {
        "customer_id": "",
        "order_id": "",
        "issue_type": "general_support",
        "workflow_status": "not_started",
        "guardrail_blocked": False,
        "action_status": "none",
    }
    for key, value in defaults.items():
        state.setdefault(key, value)
    state["current_agent"] = callback_context.agent_name
    state["last_agent_started"] = callback_context.agent_name
    history = state.get("callback_history", [])
    history.append(f"START:{callback_context.agent_name}")
    state["callback_history"] = history[-100:]
    print(f"[CALLBACK] START -> {callback_context.agent_name}")
    return None


def after_agent_callback(callback_context: CallbackContext):
    state = callback_context.state
    state["last_agent_completed"] = callback_context.agent_name
    history = state.get("callback_history", [])
    history.append(f"END:{callback_context.agent_name}")
    state["callback_history"] = history[-100:]
    if callback_context.agent_name == "final_response_agent":
        state["workflow_status"] = "completed"
    print(f"[CALLBACK] END -> {callback_context.agent_name}")
    return None
