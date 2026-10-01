from typing import Optional
from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.schemas import ActionReviewRequest
from backend.app.core.deps import require_admin

from backend.app.workflows.support_agent.tools import business_actions

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/actions")
def list_actions(status: Optional[str] = None, admin: dict = Depends(require_admin)):
    """Admin-only list of recorded business actions (N12)."""
    return business_actions.list_actions(status=status)


@router.patch("/actions/{reference}")
def review_action(
    reference: str,
    payload: ActionReviewRequest,
    admin: dict = Depends(require_admin),
):
    """Admin-only approve or reject for pending human approval actions (N12)."""
    reviewer_email = admin.get("email", "admin")
    try:
        updated = business_actions.review_action(
            reference=reference,
            new_status=payload.status,
            reason=payload.reason or "",
            reviewer=reviewer_email,
        )
        return updated
    except KeyError:
        raise HTTPException(404, f"Action '{reference}' not found.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
