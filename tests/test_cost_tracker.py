from datetime import UTC, datetime, timedelta
from pathlib import Path

from freezegun import freeze_time

from hermes_gnomes.cost_tracker import CostEvent, CostTracker
from hermes_gnomes.customer_db import init_db


def test_record_appends_event(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    tracker = CostTracker(db_path=tmp_db_path)
    with freeze_time("2026-04-13 12:00:00"):
        tracker.record(
            CostEvent(
                tool_name="etsy_listing_writer",
                model="anthropic/claude-haiku-4.5",
                input_tokens=500,
                output_tokens=200,
                cost_usd=0.003,
                action="draft_listing",
            )
        )
    total = tracker.daily_total_usd(date_utc="2026-04-13")
    assert total == 0.003


def test_daily_total_sums_all_events(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    tracker = CostTracker(db_path=tmp_db_path)
    with freeze_time("2026-04-13 08:00:00"):
        tracker.record(
            CostEvent(
                tool_name="t", model="m", input_tokens=1, output_tokens=1, cost_usd=0.01, action="a"
            )
        )
    with freeze_time("2026-04-13 20:00:00"):
        tracker.record(
            CostEvent(
                tool_name="t", model="m", input_tokens=1, output_tokens=1, cost_usd=0.02, action="a"
            )
        )
    with freeze_time("2026-04-14 08:00:00"):
        tracker.record(
            CostEvent(
                tool_name="t", model="m", input_tokens=1, output_tokens=1, cost_usd=0.99, action="a"
            )
        )

    assert tracker.daily_total_usd("2026-04-13") == 0.03
    assert tracker.daily_total_usd("2026-04-14") == 0.99


def test_rolling_baseline_average(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    tracker = CostTracker(db_path=tmp_db_path)
    base = datetime(2026, 4, 6, 12, 0, 0, tzinfo=UTC)
    costs = [0.10, 0.12, 0.08, 0.11, 0.09, 0.10, 0.11]
    for i, cost in enumerate(costs):
        with freeze_time(base + timedelta(days=i)):
            tracker.record(
                CostEvent(
                    tool_name="llm",
                    model="m",
                    input_tokens=1,
                    output_tokens=1,
                    cost_usd=cost,
                    action="a",
                )
            )
    with freeze_time("2026-04-13 12:00:00"):
        avg = tracker.rolling_average_usd(days=7)
    expected = sum(costs) / 7
    assert abs(avg - expected) < 1e-9
