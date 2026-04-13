import sqlite3
from pathlib import Path

from hermes_gnomes.customer_db import CustomerDB, init_db


def test_init_db_creates_all_tables(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = {r[0] for r in rows}
    conn.close()

    expected = {
        "customers",
        "orders",
        "email_campaigns",
        "email_sends",
        "unsubscribes",
        "approval_queue",
        "cost_events",
        "rate_limit_state",
        "image_assets",
        "schema_version",
    }
    assert expected.issubset(names)


def test_init_db_is_idempotent(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    init_db(tmp_db_path)  # must not raise
    init_db(tmp_db_path)

    conn = sqlite3.connect(tmp_db_path)
    version = conn.execute("SELECT version FROM schema_version").fetchone()
    conn.close()
    assert version[0] == 1


def test_init_db_enables_foreign_keys(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    db = CustomerDB(tmp_db_path)
    with db.connect() as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
