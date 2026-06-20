"""Price-alert evaluation.

Alerts are simple threshold rules (price above/below a target). They're checked
against live quotes; freshly-triggered alerts are returned so the realtime layer
can push them to the client.
"""

from __future__ import annotations

from datetime import datetime

from app.services import db
from app.services.market import get_quote_map


async def evaluate() -> list[dict]:
    """Check active alerts against live prices; mark & return any triggered."""
    active = db.list_alerts(only_active=True)
    if not active:
        return []

    quotes = await get_quote_map(sorted({a["symbol"].upper() for a in active}))
    triggered: list[dict] = []
    now = datetime.utcnow().isoformat()

    for alert in active:
        q = quotes.get(alert["symbol"].upper())
        if not q:
            continue
        hit = (
            (alert["direction"] == "above" and q.price >= alert["target"])
            or (alert["direction"] == "below" and q.price <= alert["target"])
        )
        if hit:
            db.mark_alert_triggered(alert["id"], now)
            triggered.append({**alert, "triggered_at": now, "price": q.price})
    return triggered
