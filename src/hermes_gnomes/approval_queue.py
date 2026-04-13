"""SQLite-backed approval queue with persistent re-ping schedule.

Approval semantics:
- Items persist indefinitely until the owner decides them. No auto-reject.
- Re-ping schedule (hours) applied relative to enqueue time.
  Default: [3, 6] — ping at 3h, then again at 6h after enqueue, then stop pinging.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass
class QueueItem:
    id: int
    platform: str
    action: str
    payload: dict
    reason: str | None
    status: str
    created_at: str
    last_pinged_at: str | None
    ping_count: int
    decided_at: str | None
    decided_by: str | None


class ApprovalQueue:
    def __init__(self, *, db_path: Path, reping_schedule_hours: list[int]) -> None:
        self.db_path = db_path
        self.reping_schedule_hours = sorted(reping_schedule_hours)

    def enqueue(
        self,
        *,
        platform: str,
        action: str,
        payload: dict,
        reason: str | None,
    ) -> int:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO approval_queue
                    (platform, action, payload_json, reason, status, created_at, ping_count)
                VALUES (?, ?, ?, ?, 'pending', ?, 0)
                """,
                (platform, action, json.dumps(payload, ensure_ascii=False), reason, now),
            )
            conn.commit()
            return int(cur.lastrowid)

    def list_pending(self) -> list[QueueItem]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM approval_queue WHERE status = 'pending' ORDER BY created_at"
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get(self, qid: int) -> QueueItem:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE id = ?", (qid,)
            ).fetchone()
        if row is None:
            raise KeyError(f"approval_queue id {qid} not found")
        return self._row_to_item(row)

    def mark_decided(self, qid: int, *, decision: str, decided_by: str) -> None:
        if decision not in {"approved", "rejected", "edited"}:
            raise ValueError(
                f"decision must be approved|rejected|edited, got {decision}"
            )
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE approval_queue
                SET status = ?, decided_at = ?, decided_by = ?
                WHERE id = ?
                """,
                (decision, now, decided_by, qid),
            )
            conn.commit()

    def mark_pinged(self, qid: int) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE approval_queue
                SET last_pinged_at = ?, ping_count = ping_count + 1
                WHERE id = ?
                """,
                (now, qid),
            )
            conn.commit()

    def items_due_for_reping(self) -> list[QueueItem]:
        """Return pending items whose next scheduled re-ping is due.

        An item is due if:
          ping_count < len(reping_schedule_hours)
          AND
          now >= created_at + reping_schedule_hours[ping_count] hours
        """
        now = datetime.now(UTC)
        due: list[QueueItem] = []
        for item in self.list_pending():
            if item.ping_count >= len(self.reping_schedule_hours):
                continue
            threshold_hours = self.reping_schedule_hours[item.ping_count]
            created = datetime.fromisoformat(item.created_at)
            if now >= created + timedelta(hours=threshold_hours):
                due.append(item)
        return due

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> QueueItem:
        return QueueItem(
            id=int(row["id"]),
            platform=row["platform"],
            action=row["action"],
            payload=json.loads(row["payload_json"]),
            reason=row["reason"],
            status=row["status"],
            created_at=row["created_at"],
            last_pinged_at=row["last_pinged_at"],
            ping_count=int(row["ping_count"]),
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
        )
