"""Lightweight SQLite persistence for positions and transactions.

Deliberately simple and synchronous (SQLite is fast for single-user). The
schema is intentionally free of any secret material — no keys, no seeds.
Swap for Postgres + SQLAlchemy when going multi-user.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "hr5_invest.db"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                asset_class TEXT NOT NULL,
                quantity REAL NOT NULL,
                avg_price REAL NOT NULL,
                source TEXT DEFAULT 'manual'
            );
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                fee REAL DEFAULT 0,
                timestamp TEXT NOT NULL,
                note TEXT
            );
            CREATE TABLE IF NOT EXISTS snapshots (
                day TEXT PRIMARY KEY,          -- YYYY-MM-DD (one per day)
                total_value REAL NOT NULL,
                total_pnl REAL NOT NULL,
                taken_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,       -- above | below
                target REAL NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT              -- NULL until fired
            );
            """
        )


def new_id() -> str:
    return uuid.uuid4().hex


def list_positions() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM positions")]


def upsert_position(pos: dict) -> dict:
    pos = {**pos}
    if not pos.get("id"):  # None or missing — generate a fresh id
        pos["id"] = new_id()
    with _conn() as c:
        c.execute(
            """INSERT INTO positions (id, symbol, asset_class, quantity, avg_price, source)
               VALUES (:id, :symbol, :asset_class, :quantity, :avg_price, :source)
               ON CONFLICT(id) DO UPDATE SET
                 symbol=excluded.symbol, asset_class=excluded.asset_class,
                 quantity=excluded.quantity, avg_price=excluded.avg_price,
                 source=excluded.source""",
            pos,
        )
    return pos


def delete_position(pos_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM positions WHERE id = ?", (pos_id,))


def list_transactions(limit: int = 50) -> list[dict]:
    with _conn() as c:
        return [
            dict(r)
            for r in c.execute(
                "SELECT * FROM transactions ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        ]


def add_transaction(tx: dict) -> dict:
    tx = {**tx}
    if not tx.get("id"):
        tx["id"] = new_id()
    with _conn() as c:
        c.execute(
            """INSERT INTO transactions (id, symbol, side, quantity, price, fee, timestamp, note)
               VALUES (:id, :symbol, :side, :quantity, :price, :fee, :timestamp, :note)""",
            tx,
        )
    return tx


# --- snapshots (performance history) ------------------------------------
def record_snapshot(day: str, total_value: float, total_pnl: float, taken_at: str) -> None:
    """Idempotent per-day: the latest value of the day wins."""
    with _conn() as c:
        c.execute(
            """INSERT INTO snapshots (day, total_value, total_pnl, taken_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(day) DO UPDATE SET
                 total_value=excluded.total_value,
                 total_pnl=excluded.total_pnl,
                 taken_at=excluded.taken_at""",
            (day, total_value, total_pnl, taken_at),
        )


def list_snapshots(limit: int = 730) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM snapshots ORDER BY day ASC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]


# --- alerts -------------------------------------------------------------
def list_alerts(only_active: bool = False) -> list[dict]:
    q = "SELECT * FROM alerts"
    if only_active:
        q += " WHERE triggered_at IS NULL"
    with _conn() as c:
        return [dict(r) for r in c.execute(q + " ORDER BY created_at DESC")]


def add_alert(alert: dict) -> dict:
    alert = {**alert}
    if not alert.get("id"):
        alert["id"] = new_id()
    with _conn() as c:
        c.execute(
            """INSERT INTO alerts (id, symbol, direction, target, note, created_at, triggered_at)
               VALUES (:id, :symbol, :direction, :target, :note, :created_at, :triggered_at)""",
            alert,
        )
    return alert


def delete_alert(alert_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))


def mark_alert_triggered(alert_id: str, when: str) -> None:
    with _conn() as c:
        c.execute("UPDATE alerts SET triggered_at = ? WHERE id = ?", (when, alert_id))
