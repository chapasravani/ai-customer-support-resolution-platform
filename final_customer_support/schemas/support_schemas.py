from typing import List
from pydantic import BaseModel, Field


class InvestigationResult(BaseModel):
    issue: str = Field(description="Customer's main issue")
    cause: str = Field(description="Confirmed or best-supported cause")
    facts: List[str] = Field(description="Confirmed facts")
    missing_information: List[str] = Field(default_factory=list, description="Information still needed")
    applicable_policy: str = Field(description="Applicable policy")
    resolution_options: List[str] = Field(description="Available resolution options")
    confidence: str = Field(description="High, medium, or low confidence")
    requires_human: bool = Field(description="Whether human intervention is required")


class ResolutionResult(BaseModel):
    resolution_type: str = Field(description="EXECUTE, RECOMMEND, REQUEST_INFORMATION, or ESCALATE")
    action: str = Field(description="Refund, replacement, cancellation, support case, or no action")
    resolution: str = Field(description="Recommended or executed resolution")
    reason: str = Field(description="Reason for the resolution")
    eligible: bool = Field(description="Whether the requested action is eligible")
    action_reference: str = Field(default="", description="Reference returned by an executed action")
    requires_human: bool = Field(description="Whether human support is required")


class EscalationResult(BaseModel):
    should_escalate: bool = Field(description="Whether to escalate")
    case_id: str = Field(default="", description="Human support case ID")
    priority: str = Field(default="medium", description="low, medium, high, or urgent")
    customer_id: str = Field(default="", description="Verified customer ID")
    order_id: str = Field(default="", description="Verified order ID")
    reason: str = Field(description="Reason for escalation or non-escalation")
    verified_facts: List[str] = Field(default_factory=list)
    investigation_summary: str = Field(default="")
    applicable_policy: str = Field(default="")
    attempted_actions: List[str] = Field(default_factory=list)
    recommended_action: str = Field(description="Recommended human next action")
