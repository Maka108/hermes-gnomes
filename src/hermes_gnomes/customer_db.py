"""SQLite-backed customer + marketing data store.

Tables:
  customers          - one row per known customer (email hashed)
  orders             - fulfilled purchases
  email_campaigns    - defined campaigns
  email_sends        - join of campaign x customer with delivery metadata
  unsubscribes       - append-only unsubscribe log
  approval_queue     - pending approvals with re-ping scheduling
  cost_events        - per-LLM-call / per-tool-call cost log
  rate_limit_state   - per-tool windowed counters
  image_assets       - metadata for synced product photos
  schema_version     - single-row migration tracker
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS customers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email_hash      TEXT NOT NULL UNIQUE,
    email_cipher    BLOB,
    display_name    TEXT,
    first_seen      TEXT NOT NULL,
    last_contact    TEXT,
    lifetime_value  REAL NOT NULL DEFAULT 0,
    tags            TEXT,
    unsubscribed    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_customers_unsubscribed ON customers(unsubscribed);

CREATE TABLE IF NOT EXISTS orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id     INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    platform        TEXT NOT NULL,
    platform_order_id TEXT NOT NULL,
    sku             TEXT,
    amount_cents    INTEGER NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'USD',
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL,
    UNIQUE(platform, platform_order_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);

CREATE TABLE IF NOT EXISTS email_campaigns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    subject         TEXT NOT NULL,
    body_template   TEXT NOT NULL,
    segment         TEXT,
    scheduled_at    TEXT,
    status          TEXT NOT NULL DEFAULT 'draft',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_sends (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    campaign_id     INTEGER NOT NULL REFERENCES email_campaigns(id) ON DELETE CASCADE,
    customer_id     INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    sent_at         TEXT,
    opened_at       TEXT,
    clicked_at      TEXT,
    UNIQUE(campaign_id, customer_id)
);

CREATE TABLE IF NOT EXISTS unsubscribes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email_hash      TEXT NOT NULL,
    source          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_unsubscribes_hash ON unsubscribes(email_hash);

CREATE TABLE IF NOT EXISTS approval_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    platform        TEXT NOT NULL,
    action          TEXT NOT NULL,
    payload_json    TEXT NOT NULL,
    reason          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    last_pinged_at  TEXT,
    ping_count      INTEGER NOT NULL DEFAULT 0,
    decided_at      TEXT,
    decided_by      TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_queue_status ON approval_queue(status);

CREATE TABLE IF NOT EXISTS cost_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL DEFAULT 0,
    action          TEXT
);

CREATE INDEX IF NOT EXISTS idx_cost_events_ts ON cost_events(ts);

CREATE TABLE IF NOT EXISTS rate_limit_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name       TEXT NOT NULL,
    window_start    TEXT NOT NULL,
    window_size_sec INTEGER NOT NULL,
    count           INTEGER NOT NULL DEFAULT 0,
    UNIQUE(tool_name, window_start, window_size_sec)
);

CREATE TABLE IF NOT EXISTS image_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL,
    external_id     TEXT,
    local_path      TEXT NOT NULL UNIQUE,
    filename        TEXT NOT NULL,
    sha256          TEXT NOT NULL,
    width           INTEGER,
    height          INTEGER,
    bytes           INTEGER NOT NULL,
    fetched_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_image_assets_sha ON image_assets(sha256);
"""


def init_db(path: Path) -> None:
    """Create the DB file and all tables if they don't exist.

    Idempotent: safe to call on every service start. Enables WAL journal
    mode so Phase 1's concurrent tool-call workers can read while a
    writer holds the write lock.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        cur = conn.execute("SELECT version FROM schema_version")
        row = cur.fetchone()
        if row is None:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    finally:
        conn.close()


class CustomerDB:
    """Thin handle around a SQLite DB. Returns connections with FKs enabled."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_customer(
        self,
        *,
        email_hash: str,
        email_cipher: bytes,
        display_name: str | None,
        first_seen: str,
    ) -> int:
        """Insert a customer, or update display_name/email_cipher if they already exist.

        Returns the customer row id.
        """
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM customers WHERE email_hash = ?", (email_hash,)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE customers
                    SET email_cipher = ?, display_name = ?
                    WHERE id = ?
                    """,
                    (email_cipher, display_name, existing["id"]),
                )
                return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO customers (email_hash, email_cipher, display_name, first_seen)
                VALUES (?, ?, ?, ?)
                """,
                (email_hash, email_cipher, display_name, first_seen),
            )
            return int(cur.lastrowid)

    def mark_unsubscribed(self, *, email_hash: str, source: str, at: str) -> None:
        """Flag customer as unsubscribed and append an audit row."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE customers SET unsubscribed = 1 WHERE email_hash = ?",
                (email_hash,),
            )
            conn.execute(
                """
                INSERT INTO unsubscribes (email_hash, source, created_at)
                VALUES (?, ?, ?)
                """,
                (email_hash, source, at),
            )

    def record_order(
        self,
        *,
        customer_id: int,
        platform: str,
        platform_order_id: str,
        sku: str | None,
        amount_cents: int,
        currency: str,
        created_at: str,
        status: str,
    ) -> int:
        """Insert an order. If the (platform, platform_order_id) pair already exists,
        return the existing id without modification."""
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM orders WHERE platform = ? AND platform_order_id = ?",
                (platform, platform_order_id),
            ).fetchone()
            if existing:
                return int(existing["id"])
            cur = conn.execute(
                """
                INSERT INTO orders (
                    customer_id, platform, platform_order_id, sku,
                    amount_cents, currency, created_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    customer_id,
                    platform,
                    platform_order_id,
                    sku,
                    amount_cents,
                    currency,
                    created_at,
                    status,
                ),
            )
            return int(cur.lastrowid)

    def active_customers(self) -> list[sqlite3.Row]:
        """Return all customers who are not unsubscribed."""
        with self.connect() as conn:
            return list(
                conn.execute(
                    "SELECT * FROM customers WHERE unsubscribed = 0 ORDER BY id"
                ).fetchall()
            )
