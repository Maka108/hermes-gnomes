from datetime import timedelta
from pathlib import Path

import pytest
from freezegun import freeze_time

from hermes_gnomes.config import RateLimit
from hermes_gnomes.customer_db import init_db
from hermes_gnomes.rate_limiter import RateLimiter, RateLimitExceeded


@pytest.fixture
def limiter(tmp_db_path: Path) -> RateLimiter:
    init_db(tmp_db_path)
    return RateLimiter(
        db_path=tmp_db_path,
        limits={"default": RateLimit(per_minute=5, per_day=50)},
    )


def test_allows_calls_under_limit(limiter: RateLimiter) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        for _ in range(5):
            limiter.check_and_consume("etsy_api_client")


def test_raises_when_minute_limit_hit(limiter: RateLimiter) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        for _ in range(5):
            limiter.check_and_consume("etsy_api_client")
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check_and_consume("etsy_api_client")
    assert "per_minute" in str(exc_info.value)


def test_minute_window_resets_after_minute(limiter: RateLimiter) -> None:
    with freeze_time("2026-04-13 12:00:00") as frozen:
        for _ in range(5):
            limiter.check_and_consume("etsy_api_client")
        frozen.tick(delta=timedelta(seconds=61))
        limiter.check_and_consume("etsy_api_client")  # should succeed


def test_raises_when_day_limit_hit(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    limiter = RateLimiter(
        db_path=tmp_db_path,
        limits={"default": RateLimit(per_minute=1000, per_day=3)},
    )
    with freeze_time("2026-04-13 12:00:00") as frozen:
        for _ in range(3):
            limiter.check_and_consume("tool")
            frozen.tick(delta=timedelta(seconds=61))
        with pytest.raises(RateLimitExceeded) as exc_info:
            limiter.check_and_consume("tool")
    assert "per_day" in str(exc_info.value)


def test_per_tool_specific_limit_wins_over_default(tmp_db_path: Path) -> None:
    init_db(tmp_db_path)
    limiter = RateLimiter(
        db_path=tmp_db_path,
        limits={
            "default": RateLimit(per_minute=100, per_day=1000),
            "tiktok_poster": RateLimit(per_minute=2, per_day=10),
        },
    )
    with freeze_time("2026-04-13 12:00:00"):
        limiter.check_and_consume("tiktok_poster")
        limiter.check_and_consume("tiktok_poster")
        with pytest.raises(RateLimitExceeded):
            limiter.check_and_consume("tiktok_poster")


def test_peek_does_not_consume(limiter: RateLimiter) -> None:
    with freeze_time("2026-04-13 12:00:00"):
        count, remaining = limiter.peek("etsy_api_client")
        assert count == 0
        assert remaining.per_minute == 5
        assert remaining.per_day == 50
        limiter.check_and_consume("etsy_api_client")
        count2, rem2 = limiter.peek("etsy_api_client")
        assert count2 == 1
        assert rem2.per_minute == 4
