"""Price-alert endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.models.schemas import Alert
from app.services import alerts, db

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("", response_model=list[Alert])
async def list_alerts():
    return db.list_alerts()


@router.post("", response_model=Alert)
async def create_alert(alert: Alert):
    return db.add_alert(alert.model_dump(mode="json"))


@router.delete("/{alert_id}")
async def delete_alert(alert_id: str):
    db.delete_alert(alert_id)
    return {"deleted": alert_id}


@router.post("/evaluate")
async def evaluate():
    """Manually trigger evaluation (also runs automatically over WebSocket)."""
    return {"triggered": await alerts.evaluate()}
