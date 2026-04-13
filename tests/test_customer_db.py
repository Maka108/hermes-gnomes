import sqlite3
from datetime import UTC, datetime
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


def _now() -> str:
    return datetime.now(UTC).isoformat()


def test_upsert_customer_creates_new(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    db = CustomerDB(tmp_db_path)

    cid = db.upsert_customer(
        email_hash="hash_abc",
        email_cipher=b"cipher_bytes",
        display_name="Alice",
        first_seen=_now(),
    )
    assert isinstance(cid, int)
    assert cid > 0

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (cid,)).fetchone()
    assert row["email_hash"] == "hash_abc"
    assert row["display_name"] == "Alice"
    assert row["unsubscribed"] == 0


def test_upsert_customer_updates_existing(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    db = CustomerDB(tmp_db_path)

    cid1 = db.upsert_customer(
        email_hash="hash_abc",
        email_cipher=b"cipher1",
        display_name="Alice",
        first_seen=_now(),
    )
    cid2 = db.upsert_customer(
        email_hash="hash_abc",
        email_cipher=b"cipher2",
        display_name="Alice Updated",
        first_seen=_now(),
    )
    assert cid1 == cid2

    with db.connect() as conn:
        row = conn.execute("SELECT display_name FROM customers WHERE id = ?", (cid1,)).fetchone()
    assert row["display_name"] == "Alice Updated"


def test_mark_unsubscribed_flag_and_log(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    db = CustomerDB(tmp_db_path)

    cid = db.upsert_customer(
        email_hash="hash_bob",
        email_cipher=b"cipher",
        display_name="Bob",
        first_seen=_now(),
    )
    db.mark_unsubscribed(email_hash="hash_bob", source="one_click", at=_now())

    with db.connect() as conn:
        customer = conn.execute(
            "SELECT unsubscribed FROM customers WHERE id = ?", (cid,)
        ).fetchone()
        logs = conn.execute(
            "SELECT * FROM unsubscribes WHERE email_hash = ?", ("hash_bob",)
        ).fetchall()
    assert customer["unsubscribed"] == 1
    assert len(logs) == 1
    assert logs[0]["source"] == "one_click"


def test_record_order_links_to_customer(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    db = CustomerDB(tmp_db_path)

    cid = db.upsert_customer(
        email_hash="h",
        email_cipher=b"c",
        display_name="Charlie",
        first_seen=_now(),
    )
    order_id = db.record_order(
        customer_id=cid,
        platform="etsy",
        platform_order_id="E12345",
        sku="GNOME-001",
        amount_cents=2999,
        currency="USD",
        created_at=_now(),
        status="paid",
    )
    assert order_id > 0

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    assert row["customer_id"] == cid
    assert row["amount_cents"] == 2999
    assert row["platform"] == "etsy"


def test_record_order_is_idempotent_per_platform_id(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    db = CustomerDB(tmp_db_path)
    cid = db.upsert_customer(email_hash="h", email_cipher=b"c", display_name="D", first_seen=_now())
    first = db.record_order(
        customer_id=cid,
        platform="etsy",
        platform_order_id="E999",
        sku="GNOME-002",
        amount_cents=1000,
        currency="USD",
        created_at=_now(),
        status="paid",
    )
    second = db.record_order(
        customer_id=cid,
        platform="etsy",
        platform_order_id="E999",
        sku="GNOME-002",
        amount_cents=1000,
        currency="USD",
        created_at=_now(),
        status="paid",
    )
    assert first == second


def test_customers_due_for_email_filters_unsubscribed(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    db = CustomerDB(tmp_db_path)

    active = db.upsert_customer(
        email_hash="a", email_cipher=b"c", display_name="A", first_seen=_now()
    )
    unsub = db.upsert_customer(
        email_hash="u", email_cipher=b"c", display_name="U", first_seen=_now()
    )
    db.mark_unsubscribed(email_hash="u", source="prefs", at=_now())

    active_ids = [c["id"] for c in db.active_customers()]
    assert active in active_ids
    assert unsub not in active_ids
