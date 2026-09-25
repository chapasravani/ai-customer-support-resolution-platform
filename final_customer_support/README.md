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

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Put your Gemini API key in `.env`. Never commit `.env`.

## Run ADK Web

From the parent directory:

```powershell
adk web customer_support
```

## MCP demo

Set `ENABLE_MCP=true` in `.env`, then run ADK Web. The agent can use the local stdio MCP server.

## OpenAPI demo

Start the mock API in another terminal:

```powershell
uvicorn customer_support.openapi_server:app --port 8001
```

Then set `ENABLE_OPENAPI=true` and restart ADK Web.

## Example scenarios

1. `My order ORD123 is delayed. What can I do?`
2. `My order ORD124 arrived damaged and I want a replacement.`
3. `My order ORD124 arrived damaged and I want a refund.`
4. `Please cancel ORD125.`
5. `My order ORD125 arrived damaged. I want a refund.`
6. `I have a problem with my order.`

## Safety model

Business actions are mock/local only. They validate order state and policy, are idempotent where appropriate, and high-value refunds are routed for human approval.
