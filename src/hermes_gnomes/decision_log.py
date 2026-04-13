"""Append-only decision log.

Every auto-post or approval decision writes one JSON line to memory/decisions.log.
Humans can grep it; Hermes can iterate it for weekly reports.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path


class DecisionLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        *,
        action: str,
        decision: str,
        confidence: float,
        reason: str,
        **extra: object,
    ) -> None:
        entry: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "action": action,
            "decision": decision,
            "confidence": confidence,
            "reason": reason,
        }
        entry.update(extra)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def iter_recent(self, limit: int = 100) -> Iterator[dict]:
        """Yield the last `limit` entries, newest first."""
        if not self.path.exists():
            return
        lines = self.path.read_text(encoding="utf-8").splitlines()
        for raw in reversed(lines[-limit:]):
            if not raw.strip():
                continue
            yield json.loads(raw)
