"""SQLite idempotency ledger. Survives a service restart; cleared by
make demo-reset. §11.

The `idempotency_key` is the table's PRIMARY KEY, so "exactly one account per
key" is enforced by the storage engine rather than by application logic that a
retry could race past. That is the property the demo points at (§10.1).
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    idempotency_key TEXT PRIMARY KEY,
    request_id      TEXT NOT NULL,
    legal_name      TEXT,
    client_id       TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    assigned_at     TEXT
);
"""


def _path() -> Path:
    return Path(os.environ.get("CORE_LEDGER_PATH", "core_banking/ledger.db"))


def _conn() -> sqlite3.Connection:
    p = _path()
    if p.parent != Path(""):
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def find(idempotency_key: str) -> dict | None:
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
    return dict(row) if row else None


def create_or_get(idempotency_key: str, legal_name: str | None) -> tuple[dict, bool]:
    """Insert an account for this key, or return the one already there.

    Returns `(row, created)`. `created` is False for every call after the
    first with a given key — that is what becomes `status: "duplicate"`.
    The INSERT is a single statement guarded by the PRIMARY KEY, so two
    concurrent retries cannot both create an account.
    """
    request_id = f"REQ-{uuid.uuid4().hex[:10]}"
    with closing(_conn()) as conn:
        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO accounts (idempotency_key, request_id, "
                "legal_name) VALUES (?, ?, ?)",
                (idempotency_key, request_id, legal_name),
            )
            created = cur.rowcount == 1
        row = conn.execute(
            "SELECT * FROM accounts WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
    return dict(row), created


def assign_client_id(request_id: str) -> dict | None:
    """Assign a client ID once. Re-assigning returns the original — the
    operator can press the button twice without minting a second ID."""
    client_id = f"CL-{uuid.uuid4().hex[:8].upper()}"
    with closing(_conn()) as conn:
        with conn:
            conn.execute(
                "UPDATE accounts SET client_id = ?, assigned_at = datetime('now') "
                "WHERE request_id = ? AND client_id IS NULL",
                (client_id, request_id),
            )
        row = conn.execute(
            "SELECT * FROM accounts WHERE request_id = ?", (request_id,)
        ).fetchone()
    return dict(row) if row else None


def all_accounts() -> list[dict]:
    with closing(_conn()) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM accounts ORDER BY created_at"
            ).fetchall()
        ]
