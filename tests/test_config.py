"""
Unit tests for config.py — rate limiter, backoff, ban detection.
"""
from __future__ import annotations


def test_random_delay_in_range():
    import config
    for _ in range(20):
        v = config.random_delay(5, 10)
        assert 5 <= v <= 10


def test_backoff_seconds_grows_exponentially():
    import config
    s1 = config.backoff_seconds(1)
    s3 = config.backoff_seconds(3)
    s5 = config.backoff_seconds(5)
    # With jitter, strict ordering is loose — check rough growth
    assert s3 > s1 * 1.5
    assert s5 >= s3


def test_backoff_respects_max(monkeypatch):
    import config
    monkeypatch.setattr(config, "BACKOFF_BASE_SEC", 30.0)
    monkeypatch.setattr(config, "BACKOFF_MAX_SEC", 100.0)
    for attempt in range(1, 20):
        # Upper bound of jitter is 1.25× MAX_SEC
        assert config.backoff_seconds(attempt) <= 100.0 * 1.25 + 0.001


def test_rate_limiter_persists(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    assert config.parsed_today() == 0
    config.register_parse()
    config.register_parse()
    assert config.parsed_today() == 2
    assert config.remaining_today() == config.DAILY_PARSE_CAP - 2


def test_rate_limiter_resets_on_new_day(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    # Write a counter from yesterday
    (tmp_path / "rate_limit.json").write_text(
        '{"date": "1999-01-01", "parsed": 42, "collected": 0}'
    )
    # Should read as 0 today (stale date)
    assert config.parsed_today() == 0


def test_can_parse_more_obeys_cap(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    monkeypatch.setattr(config, "DAILY_PARSE_CAP", 2)
    assert config.can_parse_more()
    config.register_parse()
    assert config.can_parse_more()
    config.register_parse()
    assert not config.can_parse_more()
