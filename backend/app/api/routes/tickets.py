from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.app.domains import models
from backend.app.api.schemas import TicketStatus, TicketStatusUpdate
from backend.app.core.deps import get_current_user, require_admin

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _serialize(t: dict) -> dict:
    return {
        "id": str(t["_id"]),
        "ticket_id": t["ticket_id"],
        "order_id": t.get("order_id", ""),
        "issue": t.get("issue", ""),
        "status": t["status"],
        "priority": t.get("priority", "medium"),
        "resolution_summary": t.get("resolution_summary", ""),
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
    }


@router.get("")
def list_tickets(status: Optional[str] = None, user: dict = Depends(get_current_user)):
    # Validate filter status if provided (M1)
    if status is not None and status.strip() != "":
        valid_statuses = {s.value for s in TicketStatus}
        if status not in valid_statuses:
            raise HTTPException(400, f"Invalid ticket status '{status}'. Valid statuses: {sorted(valid_statuses)}")

    # Admins see every ticket; customers see only their own.
    if user.get("role") == "admin":
        tickets = models.list_tickets(status=status)
    else:
        tickets = models.list_tickets(status=status, user_id=str(user["_id"]))
    return [_serialize(t) for t in tickets]


@router.get("/{ticket_id}")
def get_ticket(ticket_id: str, user: dict = Depends(get_current_user)):
    ticket = models.get_ticket(ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found.")
    if user.get("role") != "admin" and str(ticket["user_id"]) != str(user["_id"]):
        raise HTTPException(403, "You do not have access to this ticket.")
    return _serialize(ticket)


@router.patch("/{ticket_id}")
def update_ticket(
    ticket_id: str,
    payload: TicketStatusUpdate,
    admin: dict = Depends(require_admin),
):
    status_val = payload.status.value if hasattr(payload.status, "value") else str(payload.status)
    updated = models.update_ticket_status(
        ticket_id, status_val, payload.resolution_summary or ""
    )
    if not updated:
        raise HTTPException(404, "Ticket not found.")
    return _serialize(models.get_ticket(ticket_id))
