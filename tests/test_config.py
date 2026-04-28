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


def test_append_event_stamps_at_and_appends_jsonl(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "events.jsonl")
    ev = config.append_event({"job_id": "42", "kind": "applied", "note": "via Easy Apply"})
    assert ev["at"]  # auto-stamped
    assert ev["kind"] == "applied"
    # File now contains exactly one JSON line
    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 1


def test_append_event_rejects_invalid_kind(tmp_path, monkeypatch):
    import pytest
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "events.jsonl")
    with pytest.raises(ValueError, match="kind"):
        config.append_event({"job_id": "42", "kind": "hired"})


def test_append_event_rejects_missing_job_id(tmp_path, monkeypatch):
    import pytest
    import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "events.jsonl")
    with pytest.raises(ValueError, match="job_id"):
        config.append_event({"kind": "applied"})


def test_load_events_returns_empty_when_file_missing(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "no-such.jsonl")
    assert config.load_events() == []


def test_load_events_skips_malformed_lines(tmp_path, monkeypatch):
    import config
    f = tmp_path / "events.jsonl"
    f.write_text('{"job_id":"1","kind":"saved","at":"x"}\nnot-json\n{"job_id":"2","kind":"applied","at":"y"}\n')
    monkeypatch.setattr(config, "EVENTS_FILE", f)
    events = config.load_events()
    assert [e["job_id"] for e in events] == ["1", "2"]


def test_latest_status_ignores_notes_and_other_jobs(tmp_path, monkeypatch):
    import config
    events = [
        {"job_id": "A", "kind": "saved",    "at": "1"},
        {"job_id": "A", "kind": "applied",  "at": "2"},
        {"job_id": "B", "kind": "rejected", "at": "3"},
        {"job_id": "A", "kind": "note",     "at": "4", "note": "thought about it"},
    ]
    # Note doesn't move status; "applied" is latest real status for A
    assert config.latest_status(events, "A") == "applied"
    # B has its own chain
    assert config.latest_status(events, "B") == "rejected"
    # Unknown job defaults to "saved"
    assert config.latest_status(events, "C") == "saved"


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


# ---------------------------------------------------------------------------
# Profile load / save / merge / validation
# ---------------------------------------------------------------------------

def test_load_profile_returns_minimal_when_no_file(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "PROFILE_FILE", tmp_path / "profile.yml")
    # Also make career-ops fallback disappear
    monkeypatch.setattr(config, "_CAREER_OPS_PROFILE", tmp_path / "no-such-ref.yml")
    p = config.load_profile()
    assert isinstance(p, dict)
    assert "candidate" in p


def test_load_profile_reads_written_file(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "PROFILE_FILE", tmp_path / "profile.yml")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "profile.yml").write_text(
        "candidate:\n  full_name: Test User\ncompensation:\n  target_range: '€60K'\n",
        encoding="utf-8",
    )
    p = config.load_profile()
    assert p["candidate"]["full_name"] == "Test User"
    assert p["compensation"]["target_range"] == "€60K"


def test_save_profile_merges_and_persists(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "PROFILE_FILE", tmp_path / "profile.yml")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_CAREER_OPS_PROFILE", tmp_path / "no-such-ref.yml")
    # First save
    result = config.save_profile({"candidate": {"full_name": "Alice"}, "compensation": {"target_range": "€70K"}})
    assert result["candidate"]["full_name"] == "Alice"
    # Second save merges (does not wipe unrelated keys)
    result2 = config.save_profile({"compensation": {"currency": "EUR"}})
    assert result2["candidate"]["full_name"] == "Alice"
    assert result2["compensation"]["target_range"] == "€70K"
    assert result2["compensation"]["currency"] == "EUR"
    # Persisted
    reload = config.load_profile()
    assert reload["candidate"]["full_name"] == "Alice"


def test_validate_profile_rejects_non_string_target_range(tmp_path, monkeypatch):
    import pytest
    import config
    monkeypatch.setattr(config, "PROFILE_FILE", tmp_path / "profile.yml")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "_CAREER_OPS_PROFILE", tmp_path / "no-such-ref.yml")
    with pytest.raises(ValueError, match="target_range"):
        config.save_profile({"compensation": {"target_range": 70000}})


def test_save_profile_uses_career_ops_ref_as_merge_base(tmp_path, monkeypatch):
    """save_profile should load _CAREER_OPS_PROFILE as the merge base (when
    PROFILE_FILE doesn't exist yet), apply the patch on top, write to
    PROFILE_FILE, and leave _CAREER_OPS_PROFILE untouched."""
    import yaml
    import config

    ref_profile_path = tmp_path / "ref-profile.yml"
    profile_file_path = tmp_path / "profile.yml"

    # Write a known reference profile
    ref_data = {
        "candidate": {"full_name": "Test User", "location": "Lisbon"},
        "narrative": {"headline": "Senior Engineer"},
        "compensation": {"currency": "EUR"},
    }
    ref_profile_path.write_text(
        yaml.dump(ref_data, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(config, "_CAREER_OPS_PROFILE", ref_profile_path)
    monkeypatch.setattr(config, "PROFILE_FILE", profile_file_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)

    # PROFILE_FILE does not exist yet — merge base must come from _CAREER_OPS_PROFILE
    assert not profile_file_path.exists()

    result = config.save_profile({"compensation": {"target_range": "€60K"}})

    # Patched field present
    assert result["compensation"]["target_range"] == "€60K"
    # Reference fields also present (merge base was loaded correctly)
    assert result["candidate"]["full_name"] == "Test User"
    assert result["narrative"]["headline"] == "Senior Engineer"
    # PROFILE_FILE was created
    assert profile_file_path.exists()
    # _CAREER_OPS_PROFILE was NOT modified (reference stays clean)
    ref_reload = yaml.safe_load(ref_profile_path.read_text(encoding="utf-8"))
    assert "target_range" not in ref_reload.get("compensation", {})


# ---------------------------------------------------------------------------
# match_threshold settings
# ---------------------------------------------------------------------------

def test_default_settings_includes_match_threshold(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    s = config._default_settings()
    assert s["match_threshold"] == 80


def test_save_settings_rejects_invalid_match_threshold(tmp_path, monkeypatch):
    import pytest
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    # Out-of-range integer
    with pytest.raises(ValueError, match="match_threshold"):
        config.save_settings({"match_threshold": 150})
    # Negative
    with pytest.raises(ValueError, match="match_threshold"):
        config.save_settings({"match_threshold": -5})
    # Wrong type
    with pytest.raises(ValueError, match="match_threshold"):
        config.save_settings({"match_threshold": "high"})


def test_apply_preset_sets_match_threshold(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert config.apply_preset("stealth")["match_threshold"] == 85
    assert config.apply_preset("regular")["match_threshold"] == 80
    assert config.apply_preset("fast")["match_threshold"] == 70


def test_effective_threshold_respects_user_setting(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    config.save_settings({"match_threshold": 65})
    assert config.effective_threshold() == 65


def test_append_and_load_score(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "SCORES_FILE", tmp_path / "scores.jsonl")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    score = {"match_pct": 85, "summary": "Good fit", "skills": [], "gaps": []}
    config.append_score("42", score)
    config.append_score("42", {**score, "match_pct": 90})  # newer, should win
    config.append_score("99", {**score, "match_pct": 50})
    result = config.load_score("42")
    assert result is not None
    assert result["match_pct"] == 90
    assert result["job_id"] == "42"
    assert "cached_at" in result
    # Different job not affected
    assert config.load_score("99")["match_pct"] == 50
    # Unknown job returns None
    assert config.load_score("9999") is None
