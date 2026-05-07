from __future__ import annotations

import pytest

from strava_connect.rate_limiter import DailyLimitReached, RateLimiter, _next_quarter_hour


def test_parse_headers_nominal() -> None:
    rl = RateLimiter()
    rl.update({"X-ReadRateLimit-Usage": "10,250", "X-ReadRateLimit-Limit": "100,1000"})
    assert rl.state.usage_15min == 10
    assert rl.state.usage_daily == 250
    assert rl.state.limit_15min == 100
    assert rl.state.limit_daily == 1000


def test_parse_headers_lowercase() -> None:
    # httpx normalise généralement, mais on couvre les deux casses.
    rl = RateLimiter()
    rl.update({"x-readratelimit-usage": "5,100", "x-readratelimit-limit": "100,1000"})
    assert rl.state.usage_15min == 5
    assert rl.state.usage_daily == 100


def test_parse_headers_invalid_format_keeps_state() -> None:
    rl = RateLimiter()
    rl.update({"X-ReadRateLimit-Usage": "garbage", "X-ReadRateLimit-Limit": "100,1000"})
    # Le state n'a pas été corrompu (usage reste à 0).
    assert rl.state.usage_15min == 0
    assert rl.state.usage_daily == 0


def test_parse_headers_missing_does_nothing() -> None:
    rl = RateLimiter()
    rl.state.usage_15min = 50
    rl.update({})  # pas de headers Strava
    assert rl.state.usage_15min == 50  # inchangé


def test_before_request_below_threshold_does_not_sleep() -> None:
    rl = RateLimiter()
    rl.update({"X-ReadRateLimit-Usage": "10,100", "X-ReadRateLimit-Limit": "100,1000"})

    sleep_calls: list[float] = []
    rl.before_request(sleep=sleep_calls.append, now=lambda: 1_000.0)
    assert sleep_calls == []


def test_before_request_above_15min_threshold_sleeps_until_next_quarter() -> None:
    rl = RateLimiter()
    rl.update({"X-ReadRateLimit-Usage": "95,500", "X-ReadRateLimit-Limit": "100,1000"})

    # 12h00m30s pile → prochaine frontière à 12h15 (=14m30s d'attente).
    fake_now = 12 * 3600 + 30  # depuis epoch UTC arbitraire
    sleep_calls: list[float] = []
    rl.before_request(sleep=sleep_calls.append, now=lambda: float(fake_now))

    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(14 * 60 + 30, abs=1)
    # Reset implicite après la fenêtre
    assert rl.state.usage_15min == 0


def test_before_request_above_daily_threshold_raises() -> None:
    rl = RateLimiter()
    rl.update({"X-ReadRateLimit-Usage": "10,950", "X-ReadRateLimit-Limit": "100,1000"})

    with pytest.raises(DailyLimitReached):
        rl.before_request(sleep=lambda _: None, now=lambda: 0.0)


def test_wait_after_429_uses_retry_after_header() -> None:
    rl = RateLimiter()
    sleep_calls: list[float] = []
    rl.wait_after_429({"Retry-After": "42"}, sleep=sleep_calls.append, now=lambda: 0.0)
    assert sleep_calls == [42.0]


def test_wait_after_429_falls_back_to_next_quarter() -> None:
    rl = RateLimiter()
    sleep_calls: list[float] = []
    fake_now = 12 * 3600 + 30
    rl.wait_after_429({}, sleep=sleep_calls.append, now=lambda: float(fake_now))
    assert len(sleep_calls) == 1
    assert sleep_calls[0] == pytest.approx(14 * 60 + 30, abs=1)


def test_next_quarter_hour_boundaries() -> None:
    # À 00:00:00 → 00:15:00 (900s)
    assert _next_quarter_hour(0) == 900
    # À 00:14:59 → 00:15:00
    assert _next_quarter_hour(14 * 60 + 59) == 900
    # À 00:15:00 → 00:30:00 (1800s) — strictement la suivante
    assert _next_quarter_hour(900) == 1800
