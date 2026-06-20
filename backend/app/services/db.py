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
            """
        )


def new_id() -> str:
    return uuid.uuid4().hex


def list_positions() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM positions")]


def upsert_position(pos: dict) -> dict:
    pos = {**pos}
    pos.setdefault("id", new_id())
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
    tx.setdefault("id", new_id())
    with _conn() as c:
        c.execute(
            """INSERT INTO transactions (id, symbol, side, quantity, price, fee, timestamp, note)
               VALUES (:id, :symbol, :side, :quantity, :price, :fee, :timestamp, :note)""",
            tx,
        )
    return tx
