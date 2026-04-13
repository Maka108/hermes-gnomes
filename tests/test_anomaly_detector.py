from datetime import UTC, datetime, timedelta
from pathlib import Path

from freezegun import freeze_time

from hermes_gnomes.anomaly_detector import AnomalyDetector, AnomalyReport
from hermes_gnomes.cost_tracker import CostEvent, CostTracker
from hermes_gnomes.customer_db import init_db


def _seed_baseline(tracker: CostTracker, daily_usd: float, days: int) -> None:
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
    for i in range(days):
        with freeze_time(base + timedelta(days=i)):
            tracker.record(
                CostEvent(
                    tool_name="llm",
                    model="m",
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=daily_usd,
                    action="a",
                )
            )


def test_not_anomalous_when_today_under_threshold(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    tracker = CostTracker(db_path=tmp_db_path)
    _seed_baseline(tracker, daily_usd=0.10, days=7)

    with freeze_time("2026-04-13 14:00:00"):
        tracker.record(
            CostEvent(
                tool_name="llm",
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.20,
                action="a",
            )
        )
        detector = AnomalyDetector(tracker=tracker, baseline_days=7, multiplier=3.0)
        report = detector.check()

    assert isinstance(report, AnomalyReport)
    assert not report.anomalous
    assert report.today_usd == 0.20
    assert abs(report.baseline_usd - 0.10) < 1e-9


def test_anomalous_when_today_exceeds_threshold(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    tracker = CostTracker(db_path=tmp_db_path)
    _seed_baseline(tracker, daily_usd=0.10, days=7)

    with freeze_time("2026-04-13 14:00:00"):
        tracker.record(
            CostEvent(
                tool_name="llm",
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.50,
                action="runaway",
            )
        )
        detector = AnomalyDetector(tracker=tracker, baseline_days=7, multiplier=3.0)
        report = detector.check()

    assert report.anomalous
    assert report.today_usd == 0.50
    assert report.ratio >= 3.0


def test_not_anomalous_when_baseline_is_zero(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    tracker = CostTracker(db_path=tmp_db_path)

    with freeze_time("2026-04-13 14:00:00"):
        tracker.record(
            CostEvent(
                tool_name="llm",
                model="m",
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.05,
                action="first",
            )
        )
        detector = AnomalyDetector(tracker=tracker, baseline_days=7, multiplier=3.0)
        report = detector.check()

    assert not report.anomalous
    assert report.baseline_usd == 0.0
