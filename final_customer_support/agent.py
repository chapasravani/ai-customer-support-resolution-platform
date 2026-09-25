import json
import os
import sys
from pathlib import Path

from google.adk.agents import Agent, SequentialAgent, ParallelAgent, LoopAgent
from google.adk.tools import AgentTool, exit_loop, LongRunningFunctionTool
from google.adk.tools.tool_context import ToolContext
try:
    from google.adk.models.lite_llm import LiteLlm
except ImportError:
    LiteLlm = None
from google.genai import types
try:
    from backend.rag.context import retrieve_support_context
except ImportError:
    from rag.context import retrieve_support_context
try:
    from google.adk.tools.openapi_tool import OpenAPIToolset
except ImportError:
    OpenAPIToolset = None

try:
    from .schemas.support_schemas import (
        InvestigationResult,
        ResolutionResult,
        EscalationResult,
    )
    from .callbacks import before_agent_callback, after_agent_callback
    from .guardrails import support_guardrail
    from .tools.business_actions import (
        create_refund_request,
        create_replacement_request,
        create_cancellation_request,
        create_support_case,
    )
    from .tools.long_running import start_carrier_investigation
except ImportError:
    from schemas.support_schemas import (
        InvestigationResult,
        ResolutionResult,
        EscalationResult,
    )
    from callbacks import before_agent_callback, after_agent_callback
    from guardrails import support_guardrail
    from tools.business_actions import (
        create_refund_request,
        create_replacement_request,
        create_cancellation_request,
        create_support_case,
    )
    from tools.long_running import start_carrier_investigation


# ============================================================
# MODEL CONFIGURATION
# ============================================================
PROVIDER = os.getenv("PROVIDER", "gemini").lower()
MODEL_NAME = os.getenv("MODEL", "gemini-3.5-flash-lite")

if PROVIDER == "gemini":
    MODEL = MODEL_NAME
else:
    MODEL = LiteLlm(model=MODEL_NAME)

DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "1024"))

DEFAULT_GENERATION_CONFIG = types.GenerateContentConfig(
    max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
)

STRUCTURED_GENERATION_CONFIG = types.GenerateContentConfig(
    temperature=0.1,
    max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
)

DATA_DIR = Path(__file__).parent / "data"

ENABLE_MCP = os.getenv(
    "ENABLE_MCP",
    "false",
).lower() == "true"

ENABLE_OPENAPI = os.getenv(
    "ENABLE_OPENAPI",
    "false",
).lower() == "true"

OPENAPI_SPEC = Path(__file__).parent / "openapi.yaml"


# ============================================================
# DATA HELPERS
# ============================================================

def load_json(filename: str) -> dict:
    path = DATA_DIR / filename

    try:
        return json.loads(
            path.read_text(encoding="utf-8")
        )

    except FileNotFoundError:
        return {
            "error": f"Data file '{filename}' was not found."
        }

    except json.JSONDecodeError:
        return {
            "error": f"Data file '{filename}' contains invalid JSON."
        }


# ============================================================
# CUSTOMER TOOL
# ============================================================

def get_customer_details(customer_id: str) -> dict:
    """Retrieve verified customer/account information."""

    customers = load_json("customers.json")

    if "error" in customers:
        return customers

    customer = customers.get(customer_id)

    if not customer:
        return {
            "error": f"Customer '{customer_id}' was not found."
        }

    return {
        "customer_id": customer_id,
        **customer,
    }


# ============================================================
# ORDER TOOL
# ============================================================

def get_order_details(
    order_id: str,
    tool_context: ToolContext = None,
) -> dict:
    """Retrieve verified order, delivery and shipment information."""

    orders = load_json("orders.json")

    if "error" in orders:
        return orders

    order = orders.get(order_id)

    if not order:
        return {
            "error": f"Order '{order_id}' was not found."
        }

    result = {
        "order_id": order_id,
        **order,
    }

    if tool_context is not None:
        tool_context.state["resolved_customer_id"] = order.get(
            "customer_id",
            "",
        )

    return result


# ============================================================
# POLICY TOOL
# ============================================================

def get_policy_details(policy_name: str) -> dict:
    """Retrieve a verified support policy."""

    policies = load_json("policies.json")

    if "error" in policies:
        return policies

    policy = policies.get(policy_name)

    if not policy:
        return {
            "error": f"Policy '{policy_name}' was not found."
        }

    return {
        "policy": policy_name,
        **policy,
    }


# ============================================================
# STATE INITIALIZATION TOOL
# ============================================================

def initialize_support_state(
    customer_id: str = "",
    order_id: str = "",
    issue_type: str = "general_support",
    tool_context: ToolContext = None,
) -> dict:
    """Initialize case state and derive customer_id from a verified order."""

    if tool_context is None:
        return {
            "status": "error",
            "message": "Tool context was not provided.",
        }

    resolved_customer = customer_id or ""

    if order_id:
        orders = load_json("orders.json")

        order = (
            orders.get(order_id)
            if "error" not in orders
            else None
        )

        if order:
            resolved_customer = (
                resolved_customer
                or order.get("customer_id", "")
            )

            tool_context.state[
                "order_identity_verified"
            ] = True

        else:
            tool_context.state[
                "order_identity_verified"
            ] = False

    tool_context.state.update(
        {
            "customer_id": resolved_customer,
            "order_id": order_id or "",
            "issue_type": issue_type or "general_support",
            "workflow_status": "initialized",
            "guardrail_blocked": False,
        }
    )

    return {
        "status": "success",
        "customer_id": resolved_customer,
        "order_id": order_id or "",
        "issue_type": issue_type or "general_support",
    }


# ============================================================
# WORKFLOW COMPLETE TOOL
# ============================================================

def mark_workflow_complete(
    tool_context: ToolContext,
) -> dict:
    """Mark the support workflow complete."""

    tool_context.state["workflow_status"] = "completed"

    return {
        "status": "completed",
    }


# ============================================================
# AGENT BUILDER FACTORY
# ============================================================

def build_agent_tree(target_model=None):
    if target_model is None:
        m = MODEL
    elif PROVIDER == "gemini" and isinstance(target_model, str):
        m = target_model
    elif LiteLlm is not None and isinstance(target_model, str):
        m = LiteLlm(model=target_model)
    else:
        m = target_model

    state_agent_inst = Agent(
        model=m,
        name="state_manager",
        description="Extracts case identifiers and initializes safe session state.",
        instruction="""
Read the customer request.

Extract customer_id and order_id only when explicitly present.

Classify the issue as one of:
- damaged_order
- refund_request
- replacement_request
- return_request
- cancellation_request
- delivery_issue
- missing_delivery
- general_support

Call initialize_support_state exactly once.

Never invent identifiers.

If an order_id is provided, the tool may derive
the verified customer_id from the order record.
""",
        tools=[
            initialize_support_state
        ],
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    support_manager_inst = Agent(
        model=m,
        name="support_manager",
        description="Analyzes the support request and prepares a specialist investigation brief.",
        instruction="""
You are the Support Manager.

Convert the customer request into a concise investigation brief.

Identify:
- the problem
- requested outcome
- known IDs
- information specialists must verify

Do not solve the case.

Do not invent facts or IDs.
""",
        output_key="support_request",
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    order_agent_inst = Agent(
        model=m,
        name="order_agent",
        description="Retrieves verified order and shipment information.",
        instruction="""
You are the Order Agent.

Use get_order_details when order_id is available.

Return verified:
- status
- expected delivery
- carrier
- tracking
- delay reason
- customer_id
- amount

If the order is missing, clearly report that.

Never invent order facts.
""",
        tools=[
            get_order_details
        ],
        output_key="order_info",
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    customer_agent_inst = Agent(
        model=m,
        name="customer_agent",
        description="Retrieves verified CRM/account information.",
        instruction="""
You are the Customer Agent.

Use the session customer_id when available.

It may have been resolved from the verified order.

Call get_customer_details and return only verified
account facts.

If unavailable, report that clearly.

Never invent customer information.
""",
        tools=[
            get_customer_details
        ],
        output_key="customer_info",
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    knowledge_agent_inst = Agent(
        model=m,
        name="knowledge_agent",
        description="Retrieves and explains the applicable support policy.",
        instruction="""
You are the Knowledge Agent.

Choose the most relevant policy using the customer request
and verified order facts.

Use:
- damaged_order for delivered/damaged claims
- late_delivery for delayed orders
- cancelled_order for cancelled orders
- general_support otherwise

First use get_policy_details to retrieve the structured
policy information.

Then use retrieve_support_context to search the
admin-uploaded support documents for relevant policy,
procedure, or knowledge information.

Your final policy findings must clearly include:

1. The structured policy information returned by
   get_policy_details.
2. Any relevant information retrieved from the RAG
   knowledge base.
3. Any human-review or approval requirement found
   in either source.

Treat RAG results as verified support knowledge only when
they are actually returned by retrieve_support_context.

Do not invent policy terms, approval rules, thresholds,
or procedures.

If the structured policy and RAG information differ,
clearly report the difference instead of silently choosing
one.
""",
        tools=[
            get_policy_details,
            retrieve_support_context,
        ],
        output_key="policy_info",
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    policy_advisor_agent_inst = Agent(
        model=m,
        name="policy_advisor",
        description="Explains policy constraints for another agent.",
        instruction="""
Explain the supplied policy's:

- allowed actions
- restrictions
- human-review requirement

Do not perform business actions.

Do not invent rules.
""",
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    investigation_agent_inst = Agent(
        model=m,
        name="investigation_agent",
        description="Combines customer, order and policy evidence into a structured finding.",
        instruction="""
You are the Investigation Agent.

Use only verified evidence supplied by the previous
workflow stages.

Review all of the following:

- support_request
- customer_info
- order_info
- policy_info

The policy_info may contain both:

1. structured policy information from get_policy_details
2. relevant support knowledge retrieved from the
   admin-uploaded RAG documents

Use the RAG information when it is relevant to the
customer's request.

Determine:

- issue
- supported cause
- verified facts
- missing information
- applicable policy
- resolution options
- confidence
- whether human intervention is required

When a policy rule, approval requirement, threshold,
or procedure comes from RAG, preserve that information
in the applicable policy or verified facts.

Do not invent policy terms or rules.

If the available evidence is insufficient or conflicting,
identify the missing information rather than guessing.

A damaged claim is not proof of damage unless
available evidence supports it.

Never claim an action was completed.
""",
        generate_content_config=STRUCTURED_GENERATION_CONFIG,
        output_schema=InvestigationResult,
        output_key="investigation",
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    investigation_review_agent_inst = Agent(
        model=m,
        name="investigation_review_agent",
        description="Checks investigation completeness and evidence quality.",
        instruction="""
Review {investigation}.

If issue, cause, facts, policy, options and
human-review decision are adequately supported,
call exit_loop.

Otherwise explain exactly what is missing so the
next investigation pass can correct it.

Never invent facts.
""",
        tools=[
            exit_loop
        ],
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        output_key="investigation_review",
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    investigation_loop_inst = LoopAgent(
        name="investigation_validation_loop",
        description="Investigate, evaluate evidence, and refine missing information.",
        sub_agents=[
            investigation_agent_inst,
            investigation_review_agent_inst,
        ],
        max_iterations=2,
    )

    resolution_agent_inst = Agent(
        model=m,
        name="resolution_agent",
        description="Makes a safe, structured resolution decision from verified investigation evidence.",
        instruction="""
You are the Resolution Decision Agent.

Your job is ONLY to decide the appropriate resolution.

Review:
- investigation
- policy_info
- order_info
- customer_info
- support_request

Do NOT call any business-action tools.
Do NOT execute refunds.
Do NOT execute replacements.
Do NOT execute cancellations.
Do NOT create support cases.

Return ONLY the required structured ResolutionResult.

Allowed resolution_type values:
- EXECUTE
- RECOMMEND
- REQUEST_INFORMATION
- ESCALATE

Allowed action values:
- refund
- replacement
- cancellation
- support case
- no action

Rules:

1. CUSTOMER AUTHORIZATION IS REQUIRED before selecting EXECUTE. Eligibility alone is NEVER authorization.
2. Treat questions such as "what can you do", "what are my options", "am I eligible", "can I get a refund", or "what is the refund policy" as informational/option-seeking. These must NOT execute a business action.
3. Use RECOMMEND for an eligible option when the customer has not explicitly authorized the action.
4. Use EXECUTE only when the customer explicitly asks for the specific action, for example "please refund my order", "I want a refund", "give me a replacement", or "cancel my order".
5. If the customer asks about multiple options without choosing one, use RECOMMEND and action="no action".
6. REQUEST_INFORMATION means required information is missing.
7. ESCALATE means human intervention is required.
8. Never claim that a business action was completed.
9. Use only verified information from the investigation and policy.
10. If the investigation says human intervention is required, use ESCALATE.
11. If evidence is insufficient or conflicting, use REQUEST_INFORMATION or ESCALATE.
12. High-value refunds requiring human approval must not be treated as completed.
13. Keep every text field concise.

The response must contain ONLY these fields:

- resolution_type
- action
- resolution
- reason
- eligible
- action_reference
- requires_human

Keep resolution and reason short.
Do not include extra fields.
Do not include markdown.
Do not include explanations outside the structured response.
""",
        generate_content_config=STRUCTURED_GENERATION_CONFIG,
        output_schema=ResolutionResult,
        output_key="resolution",
        before_agent_callback=[
            before_agent_callback,
            support_guardrail,
        ],
        after_agent_callback=after_agent_callback,
    )

    business_action_agent_inst = Agent(
        model=m,
        name="business_action_agent",
        description="Executes one authorized business action after the resolution decision.",
        instruction="""
You are the Business Action Agent.

Review:
- resolution
- investigation
- order_info
- customer_info

Execute an authorized business action ONLY when the structured resolution decision allows it.

Available tools:
- create_refund_request
- create_replacement_request
- create_cancellation_request
- create_support_case

Rules:
1. Execute at most ONE business action.
2. CUSTOMER AUTHORIZATION IS REQUIRED. Never execute merely because an action is eligible or recommended.
3. If the customer message/support_request only asks what can be done, asks for options, asks about eligibility, or asks a policy question, do NOT execute any business action.
4. If resolution.resolution_type is not EXECUTE, do not execute a refund, replacement, or cancellation.
5. If resolution.eligible is false, do not execute an action.
6. If resolution.requires_human is true, do not execute a normal automated refund, replacement, or cancellation.
7. For EXECUTE, verify that the support_request/customer request explicitly asks for the same action before calling the tool. If explicit authorization is not clear, do not call any tool.
8. Execute the matching refund, replacement, or cancellation action only after explicit authorization.
9. For ESCALATE with action "support case", create exactly one support case when explicitly requested by the resolution.
10. Use only verified order_id and customer_id from workflow state/order/customer information.
11. Never invent an order ID or customer ID.
12. Use a concise reason based only on verified evidence.
13. Never claim success unless the tool actually returns a successful result.
14. Preserve tool status and reference for the next workflow stage.
15. If the tool returns pending_human_approval, preserve that status.
16. If the tool returns rejected, preserve the rejection reason.
17. If no business action is explicitly authorized, do not call any tool.

After tool execution, give a concise result describing what was actually returned.
""",
        tools=[
            create_refund_request,
            create_replacement_request,
            create_cancellation_request,
            create_support_case,
        ],
        output_key="action_result",
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    escalation_agent_inst = Agent(
        model=m,
        name="escalation_agent",
        description="Creates a structured human-support handoff from the verified case state.",
        instruction="""
You are the Escalation Agent.

Review:
- investigation
- resolution
- action_result
- customer_info
- order_info

Determine whether human support is required.

Set should_escalate to true when:
- resolution.resolution_type is ESCALATE, or
- resolution.requires_human is true, or
- action_result shows pending_human_approval, or
- the action result clearly indicates failed/rejected execution that requires human handling.

Set should_escalate to false when the case was safely resolved without human intervention and no further human action is required.

If a support case was actually created, use its returned reference as case_id.
Do not invent a case ID.

Return ONLY the required structured EscalationResult.
Keep all text concise.
Do not claim that an action succeeded unless action_result confirms it.
""",
        generate_content_config=STRUCTURED_GENERATION_CONFIG,
        output_schema=EscalationResult,
        output_key="escalation",
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    final_response_agent_inst = Agent(
        model=m,
        name="final_response_agent",
        description="Produces a concise, warm, and professional customer-facing response.",
        instruction="""
You are SupportAI, the customer-facing AI support representative.

Your ONLY job is to write a warm, clear, and professional response directly to the customer (2 to 4 short sentences).

Information sources available in state:
- support_request, customer_info, order_info, policy_info, investigation, resolution, action_result, escalation

CRITICAL RESPONSE RULES:
1. Speak directly to the customer in natural, empathetic, and professional language.
2. NEVER use technical section headers (do NOT output headers like "**Support Request**", "**Investigation**", "**Verified Facts**", "**Resolution**", or bullet lists of internal state).
3. NEVER mention internal agents, state keys, Pydantic models, prompts, guardrails, MCP, or pipeline stages.
4. Keep the final response short and easy to read (2 to 4 sentences). Avoid long paragraphs.
5. Base all statements strictly on verified evidence from the investigation. Never invent tracking updates, delivery dates, or policies.
6. If the customer query lacks necessary information (such as an Order ID), ask for it politely and directly.
7. If an order is delayed, state the verified status and updated delivery date clearly.
8. If a human specialist review was triggered, inform the customer that their case has been created/forwarded for specialist review.
9. NEVER claim a refund, replacement, or cancellation completed unless action_result confirms successful execution.
""",
        output_key="final_response",
        generate_content_config=DEFAULT_GENERATION_CONFIG,
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    parallel_research_inst = ParallelAgent(
        name="parallel_case_research",
        description="Runs Customer, Order and Knowledge specialists concurrently.",
        sub_agents=[
            customer_agent_inst,
            order_agent_inst,
            knowledge_agent_inst,
        ],
    )

    root = SequentialAgent(
        name="customer_support_system",
        description=(
            "End-to-end AI customer support and resolution "
            "platform using Google ADK and Gemini."
        ),
        sub_agents=[
            state_agent_inst,
            support_manager_inst,
            parallel_research_inst,
            investigation_loop_inst,
            resolution_agent_inst,
            business_action_agent_inst,
            escalation_agent_inst,
            final_response_agent_inst,
        ],
        before_agent_callback=before_agent_callback,
        after_agent_callback=after_agent_callback,
    )

    return root, {
        "state_agent": state_agent_inst,
        "support_manager": support_manager_inst,
        "order_agent": order_agent_inst,
        "customer_agent": customer_agent_inst,
        "knowledge_agent": knowledge_agent_inst,
        "policy_advisor_agent": policy_advisor_agent_inst,
        "policy_advisor_tool": AgentTool(agent=policy_advisor_agent_inst),
        "investigation_agent": investigation_agent_inst,
        "investigation_review_agent": investigation_review_agent_inst,
        "investigation_loop": investigation_loop_inst,
        "resolution_agent": resolution_agent_inst,
        "business_action_agent": business_action_agent_inst,
        "escalation_agent": escalation_agent_inst,
        "final_response_agent": final_response_agent_inst,
        "parallel_research": parallel_research_inst,
    }


# ============================================================
# PRIMARY & FALLBACK AGENTS
# ============================================================

root_agent, _primary_subagents = build_agent_tree(MODEL)
globals().update(_primary_subagents)

FALLBACK_MODEL_NAME = os.getenv("FALLBACK_MODEL", "gemini-3.1-flash-lite")
if PROVIDER == "gemini" and FALLBACK_MODEL_NAME != MODEL_NAME:
    fallback_root_agent, _ = build_agent_tree(FALLBACK_MODEL_NAME)
else:
    fallback_root_agent = root_agent


# ============================================================
# MCP INTEGRATION
# ============================================================

mcp_toolset = None

if ENABLE_MCP:
    from google.adk.tools.mcp_tool import McpToolset

    from google.adk.tools.mcp_tool.mcp_session_manager import (
        StdioConnectionParams,
    )

    from mcp import StdioServerParameters

    MCP_SERVER_PATH = (
        Path(__file__).parent / "mcp_server.py"
    )

    mcp_toolset = McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=sys.executable,
                args=[
                    str(MCP_SERVER_PATH)
                ],
            )
        )
    )


# ============================================================
# MCP SPECIALIST
# ============================================================

mcp_specialist = Agent(
    model=MODEL,
    name="mcp_specialist",
    description="Uses MCP tools for CRM/order/support integration.",
    instruction="""
Use the MCP tools to retrieve verified enterprise
support information when enabled.

Never invent results.
""",
    tools=[
        mcp_toolset
    ] if mcp_toolset else [],
    output_key="mcp_info",
    generate_content_config=DEFAULT_GENERATION_CONFIG,
    before_agent_callback=before_agent_callback,
    after_agent_callback=after_agent_callback,
)


# ============================================================
# LONG-RUNNING CARRIER INVESTIGATION
# ============================================================

long_running_tool = LongRunningFunctionTool(
    func=start_carrier_investigation
)

carrier_investigation_agent = Agent(
    model=MODEL,
    name="carrier_investigation_agent",
    description="Starts a long-running carrier investigation when a case needs external investigation.",
    instruction="""
Use the long-running carrier investigation only when
shipment/tracking evidence is insufficient and an
external carrier check is appropriate.

Return the operation status and reference.
""",
    tools=[
        long_running_tool
    ],
    generate_content_config=DEFAULT_GENERATION_CONFIG,
    output_key="carrier_investigation",
    before_agent_callback=before_agent_callback,
    after_agent_callback=after_agent_callback,
)


# ============================================================
# OPENAPI INTEGRATION
# ============================================================

openapi_toolset = None

if (
    ENABLE_OPENAPI
    and OpenAPIToolset is not None
    and OPENAPI_SPEC.exists()
):
    openapi_toolset = OpenAPIToolset(
        spec_str=OPENAPI_SPEC.read_text(
            encoding="utf-8"
        ),
        spec_str_type="yaml",
    )


# ============================================================
# OPENAPI SPECIALIST
# ============================================================

openapi_agent = Agent(
    model=MODEL,
    name="openapi_specialist",
    description="Calls the mock enterprise REST API generated from OpenAPI.",
    instruction="""
Use the OpenAPI tools only when API-backed
verification or action is requested.

Never invent API results.
""",
    tools=[
        openapi_toolset
    ] if openapi_toolset else [],
    output_key="openapi_info",
    generate_content_config=DEFAULT_GENERATION_CONFIG,
    before_agent_callback=before_agent_callback,
    after_agent_callback=after_agent_callback,
)
