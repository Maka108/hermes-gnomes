"""Per-tool rate limiter backed by the customer_db.rate_limit_state table.

Enforces two windows per tool: per_minute and per_day. The hard cap is the
rightmost defense -- even if the LLM decides to call a tool 1000 times in a
loop, the tool layer fails closed.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .config import RateLimit


class RateLimitExceeded(RuntimeError):
    """Raised when a tool call would exceed the configured cap."""


@dataclass
class RemainingCapacity:
    """Remaining capacity in the current minute/day windows for a tool.

    Distinct from :class:`RateLimit` because pydantic enforces ``gt=0`` on that
    model, while remaining capacity can legitimately be zero.
    """

    per_minute: int
    per_day: int


class RateLimiter:
    def __init__(self, *, db_path: Path, limits: dict[str, RateLimit]) -> None:
        if "default" not in limits:
            raise ValueError("limits must include a 'default' RateLimit entry")
        self.db_path = db_path
        self.limits = limits

    # --- public API -------------------------------------------------

    def check_and_consume(self, tool_name: str) -> None:
        """Raise RateLimitExceeded if a call would breach the cap, otherwise
        atomically increment both minute and day windows."""
        limit = self._limit_for(tool_name)
        now = datetime.now(UTC)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            minute_count = self._window_count(conn, tool_name, 60, now)
            day_count = self._window_count(conn, tool_name, 86400, now)
            if minute_count >= limit.per_minute:
                raise RateLimitExceeded(f"{tool_name} per_minute cap {limit.per_minute} reached")
            if day_count >= limit.per_day:
                raise RateLimitExceeded(f"{tool_name} per_day cap {limit.per_day} reached")
            self._window_increment(conn, tool_name, 60, now)
            self._window_increment(conn, tool_name, 86400, now)
            conn.commit()

    def peek(self, tool_name: str) -> tuple[int, RemainingCapacity]:
        """Return (minute_count, remaining_capacity) without consuming."""
        limit = self._limit_for(tool_name)
        now = datetime.now(UTC)
        with sqlite3.connect(self.db_path) as conn:
            minute_count = self._window_count(conn, tool_name, 60, now)
            day_count = self._window_count(conn, tool_name, 86400, now)
        remaining = RemainingCapacity(
            per_minute=max(0, limit.per_minute - minute_count),
            per_day=max(0, limit.per_day - day_count),
        )
        return minute_count, remaining

    # --- internals --------------------------------------------------

    def _limit_for(self, tool_name: str) -> RateLimit:
        return self.limits.get(tool_name, self.limits["default"])

    @staticmethod
    def _window_start(now: datetime, window_size_sec: int) -> str:
        bucket = int(now.timestamp()) // window_size_sec
        start = datetime.fromtimestamp(bucket * window_size_sec, tz=UTC)
        return start.isoformat()

    def _window_count(
        self,
        conn: sqlite3.Connection,
        tool: str,
        size: int,
        now: datetime,
    ) -> int:
        start = self._window_start(now, size)
        row = conn.execute(
            """
            SELECT count FROM rate_limit_state
            WHERE tool_name = ? AND window_start = ? AND window_size_sec = ?
            """,
            (tool, start, size),
        ).fetchone()
        return int(row[0]) if row else 0

    def _window_increment(
        self,
        conn: sqlite3.Connection,
        tool: str,
        size: int,
        now: datetime,
    ) -> None:
        start = self._window_start(now, size)
        conn.execute(
            """
            INSERT INTO rate_limit_state (tool_name, window_start, window_size_sec, count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(tool_name, window_start, window_size_sec)
            DO UPDATE SET count = count + 1
            """,
            (tool, start, size),
        )
