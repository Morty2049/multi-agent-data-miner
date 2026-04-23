"""
Unit tests for config.py — rate limiter only (anti-ban helpers and delays
were removed together with the legacy CLI scraper).
"""
from __future__ import annotations


def test_rate_limiter_persists(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    assert config.parsed_today() == 0
    config.register_parse()
    config.register_parse()
    assert config.parsed_today() == 2
    assert config.remaining_today() == config.DAILY_PARSE_CAP - 2


def test_rate_limiter_resets_on_new_day(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    (tmp_path / "rate_limit.json").write_text(
        '{"date": "1999-01-01", "parsed": 42}'
    )
    assert config.parsed_today() == 0


def test_can_parse_more_obeys_cap(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
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
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DAILY_PARSE_CAP", 1)
    config.register_parse()
    config.register_parse()  # over the cap
    assert config.remaining_today() == 0  # clamped, not -1


def test_load_settings_returns_defaults_when_no_file(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    s = config.load_settings()
    assert s["mode"] == "regular"
    assert s["randomize_delays"] is True
    assert s["delays_ms"]["click_min"] == 2500
    assert s["daily_cap"] == config.DAILY_PARSE_CAP


def test_save_settings_persists_and_merges(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    result = config.save_settings({"daily_cap": 200})
    assert result["daily_cap"] == 200
    # Other fields fall back to defaults
    assert result["delays_ms"]["click_min"] == 2500
    # Persisted — reloading picks up the value
    assert config.load_settings()["daily_cap"] == 200


def test_save_settings_rejects_invalid_cap(tmp_path, monkeypatch):
    import pytest
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with pytest.raises(ValueError, match="daily_cap"):
        config.save_settings({"daily_cap": -1})


def test_save_settings_rejects_reversed_delay_pair(tmp_path, monkeypatch):
    import pytest
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with pytest.raises(ValueError, match="click_min"):
        config.save_settings({"delays_ms": {"click_min": 5000, "click_max": 3000}})


def test_save_settings_accepts_null_cap(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    result = config.save_settings({"daily_cap": None})
    assert result["daily_cap"] is None
    assert config.effective_cap() >= 10**8  # treated as unlimited


def test_apply_preset_stealth_writes_expected_values(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    result = config.apply_preset("stealth")
    assert result["mode"] == "stealth"
    assert result["daily_cap"] == 400
    assert result["delays_ms"]["between_saves_max"] == 45000


def test_apply_preset_unknown_raises(tmp_path, monkeypatch):
    import pytest
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with pytest.raises(ValueError, match="unknown preset"):
        config.apply_preset("turbo")


def test_can_parse_more_honours_settings_cap(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "RATE_LIMIT_FILE", tmp_path / "rate_limit.json")
    config.save_settings({"daily_cap": 1})
    assert config.can_parse_more()
    config.register_parse()
    assert not config.can_parse_more()


def test_env_overrides_vault_and_data_dirs(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    data = tmp_path / "data"
    monkeypatch.setenv("JOB_MINER_VAULT_DIR", str(vault))
    monkeypatch.setenv("JOB_MINER_DATA_DIR", str(data))
    import importlib
    import config
    importlib.reload(config)
    try:
        assert config.VAULT_DIR == vault.resolve()
        assert config.DATA_DIR == data.resolve()
        assert config.RATE_LIMIT_FILE == data.resolve() / "rate_limit.json"
    finally:
        monkeypatch.delenv("JOB_MINER_VAULT_DIR", raising=False)
        monkeypatch.delenv("JOB_MINER_DATA_DIR", raising=False)
        importlib.reload(config)
