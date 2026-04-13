from pathlib import Path

import pytest
from freezegun import freeze_time

from hermes_gnomes.approval_queue import ApprovalQueue
from hermes_gnomes.customer_db import init_db


@pytest.fixture
def queue(tmp_db_path: Path) -> ApprovalQueue:
    init_db(tmp_db_path)
    return ApprovalQueue(db_path=tmp_db_path, reping_schedule_hours=[3, 6])


def test_enqueue_creates_pending_item(queue: ApprovalQueue) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        qid = queue.enqueue(
            platform="etsy",
            action="create_listing",
            payload={"title": "Happy Gnome", "price": 29.99},
            reason="public_facing_listing",
        )
    assert qid > 0

    items = queue.list_pending()
    assert len(items) == 1
    assert items[0].id == qid
    assert items[0].platform == "etsy"
    assert items[0].action == "create_listing"
    assert items[0].payload == {"title": "Happy Gnome", "price": 29.99}
    assert items[0].status == "pending"
    assert items[0].ping_count == 0


def test_mark_decided_removes_from_pending(queue: ApprovalQueue) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        qid = queue.enqueue(
            platform="etsy",
            action="create_listing",
            payload={},
            reason="r",
        )
    with freeze_time("2026-04-13 12:30:00"):
        queue.mark_decided(qid, decision="approved", decided_by="owner")

    assert queue.list_pending() == []

    item = queue.get(qid)
    assert item.status == "approved"
    assert item.decided_by == "owner"


def test_items_due_for_reping_at_3_hours(queue: ApprovalQueue) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        queue.enqueue(
            platform="etsy",
            action="create_listing",
            payload={},
            reason="r",
        )

    with freeze_time("2026-04-13 14:59:00"):
        assert queue.items_due_for_reping() == []

    with freeze_time("2026-04-13 15:01:00"):
        due = queue.items_due_for_reping()
        assert len(due) == 1
        assert due[0].ping_count == 0


def test_items_due_for_reping_at_6_hours_after_first_ping(queue: ApprovalQueue) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        qid = queue.enqueue(
            platform="etsy",
            action="create_listing",
            payload={},
            reason="r",
        )
    with freeze_time("2026-04-13 15:05:00"):
        due = queue.items_due_for_reping()
        assert len(due) == 1
        queue.mark_pinged(qid)

    with freeze_time("2026-04-13 17:00:00"):
        assert queue.items_due_for_reping() == []

    with freeze_time("2026-04-13 18:05:00"):
        due = queue.items_due_for_reping()
        assert len(due) == 1
        queue.mark_pinged(qid)

    with freeze_time("2026-04-14 00:00:00"):
        assert queue.items_due_for_reping() == []


def test_items_persist_indefinitely_until_decided(queue: ApprovalQueue) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        queue.enqueue(
            platform="etsy",
            action="create_listing",
            payload={},
            reason="r",
        )
    with freeze_time("2026-05-13 12:00:00"):
        pending = queue.list_pending()
        assert len(pending) == 1


def test_payload_roundtrip_preserves_unicode(queue: ApprovalQueue) -> None:
    payload = {"title": "Gnóme with emoji 🧙"}
    with freeze_time("2026-04-13 12:00:00"):
        qid = queue.enqueue(
            platform="etsy",
            action="create_listing",
            payload=payload,
            reason="r",
        )
    item = queue.get(qid)
    assert item.payload == payload
