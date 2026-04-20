"""
Unit tests for config.py — rate limiter only (anti-ban helpers and delays
were removed together with the legacy CLI scraper).
"""
from __future__ import annotations


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
    (tmp_path / "rate_limit.json").write_text(
        '{"date": "1999-01-01", "parsed": 42}'
    )
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


def test_remaining_today_never_negative(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    monkeypatch.setattr(config, "DAILY_PARSE_CAP", 1)
    config.register_parse()
    config.register_parse()  # over the cap
    assert config.remaining_today() == 0  # clamped, not -1
