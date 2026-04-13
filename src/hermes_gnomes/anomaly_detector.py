"""Cost anomaly detector.

Compares today's LLM+tool cost against the N-day rolling average.
If today exceeds (multiplier * baseline), emits an AnomalyReport(anomalous=True).
Callers pause automated posting and alert the user.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .cost_tracker import CostTracker


@dataclass
class AnomalyReport:
    anomalous: bool
    today_usd: float
    baseline_usd: float
    ratio: float
    reason: str


class AnomalyDetector:
    def __init__(
        self,
        *,
        tracker: CostTracker,
        baseline_days: int,
        multiplier: float,
    ) -> None:
        self.tracker = tracker
        self.baseline_days = baseline_days
        self.multiplier = multiplier

    def check(self) -> AnomalyReport:
        today = datetime.now(UTC).date().isoformat()
        today_usd = self.tracker.daily_total_usd(today)
        baseline = self.tracker.rolling_average_usd(days=self.baseline_days)

        if baseline <= 0:
            return AnomalyReport(
                anomalous=False,
                today_usd=today_usd,
                baseline_usd=0.0,
                ratio=0.0,
                reason="no baseline yet",
            )
        ratio = today_usd / baseline
        anomalous = ratio >= self.multiplier
        reason = (
            f"today ${today_usd:.2f} vs baseline ${baseline:.2f} "
            f"({ratio:.1f}x threshold {self.multiplier}x)"
        )
        return AnomalyReport(
            anomalous=anomalous,
            today_usd=today_usd,
            baseline_usd=baseline,
            ratio=ratio,
            reason=reason,
        )
