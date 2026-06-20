"""Performance history from daily portfolio snapshots.

A snapshot is recorded (idempotently) once per day whenever the portfolio
summary is computed. From the snapshot series we derive real day/week/month/
year/YTD returns and an equity curve — closing the gap where only the intraday
move was available.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta


def _pct(curr: float, past: float | None) -> float | None:
    if past is None or past == 0:
        return None
    return round((curr - past) / past * 100, 2)


def _value_on_or_before(snapshots: list[dict], target: date) -> float | None:
    """Most recent snapshot value at or before ``target``."""
    chosen = None
    for s in snapshots:
        d = date.fromisoformat(s["day"])
        if d <= target:
            chosen = s["total_value"]
        else:
            break
    return chosen


def record(total_value: float, total_pnl: float) -> None:
    # Imported lazily to avoid a circular import at module load.
    from app.services import db

    now = datetime.utcnow()
    db.record_snapshot(now.date().isoformat(), total_value, total_pnl, now.isoformat())


def performance() -> dict:
    from app.services import db

    snaps = db.list_snapshots()
    if not snaps:
        return {
            "current": 0.0,
            "periods": {k: None for k in ("day", "week", "month", "year", "ytd")},
            "history_days": 0,
        }

    current = snaps[-1]["total_value"]
    today = date.fromisoformat(snaps[-1]["day"])
    periods = {
        "day": _pct(current, _value_on_or_before(snaps, today - timedelta(days=1))),
        "week": _pct(current, _value_on_or_before(snaps, today - timedelta(days=7))),
        "month": _pct(current, _value_on_or_before(snaps, today - timedelta(days=30))),
        "year": _pct(current, _value_on_or_before(snaps, today - timedelta(days=365))),
        "ytd": _pct(current, _value_on_or_before(snaps, date(today.year, 1, 1))),
    }
    return {"current": current, "periods": periods, "history_days": len(snaps)}


def equity_curve() -> list[dict]:
    from app.services import db

    return [
        {"day": s["day"], "value": s["total_value"], "pnl": s["total_pnl"]}
        for s in db.list_snapshots()
    ]
