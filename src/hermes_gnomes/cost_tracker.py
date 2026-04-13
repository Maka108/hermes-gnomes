"""Per-call cost event log for LLM and tool calls.

Writes to the cost_events table in customer_db. Aggregations power:
- the weekly report
- the anomaly_detector
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass
class CostEvent:
    tool_name: str
    model: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    action: str | None = None


class CostTracker:
    def __init__(self, *, db_path: Path) -> None:
        self.db_path = db_path

    def record(self, event: CostEvent) -> None:
        ts = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO cost_events
                    (ts, tool_name, model, input_tokens, output_tokens, cost_usd, action)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts,
                    event.tool_name,
                    event.model,
                    event.input_tokens,
                    event.output_tokens,
                    event.cost_usd,
                    event.action,
                ),
            )
            conn.commit()

    def daily_total_usd(self, date_utc: str) -> float:
        """Sum cost_usd for all events where date(ts) == date_utc (YYYY-MM-DD)."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_events WHERE substr(ts, 1, 10) = ?",
                (date_utc,),
            ).fetchone()
        return float(row[0])

    def rolling_average_usd(self, *, days: int) -> float:
        """Mean daily cost over the past `days` days excluding today."""
        now = datetime.now(UTC)
        totals: list[float] = []
        for i in range(1, days + 1):
            d = (now - timedelta(days=i)).date().isoformat()
            totals.append(self.daily_total_usd(d))
        if not totals:
            return 0.0
        return sum(totals) / len(totals)
