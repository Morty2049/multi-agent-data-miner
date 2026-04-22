"""
config.py — minimal project config for the Chrome plugin backend.

Historical note: this file used to hold LinkedIn scraping knobs
(session dir, user-agent, delays, ban detector, exponential backoff).
Those belonged to the legacy Playwright CLI (collect_queue / parse_job /
run_queue) which is retired — the Chrome extension does not need any of
that because it runs inside the user's own logged-in browser tab.

What stays:
  • VAULT_DIR / DATA_DIR / RATE_LIMIT_FILE — shared paths
  • DAILY_PARSE_CAP + rate-limiter — prevent a runaway autopilot from
    carpet-bombing the vault in one run

Reads an optional `.env` in the repo root (simple key=value parser, no
third-party dep). Real environment variables override .env values.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path


# ---------------------------------------------------------------------------
# .env loader
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent
_ENV_FILE = REPO_ROOT / ".env"


def _load_dotenv() -> None:
    if not _ENV_FILE.exists():
        return
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
#
# By default the vault and data directories live next to this file.
# `JOB_MINER_VAULT_DIR` / `JOB_MINER_DATA_DIR` override that — use them
# when the server runs from a git worktree or container where `__file__`
# isn't next to the real vault. Without overrides, each checkout gets
# its own vault and saved vacancies silently diverge.

def _resolved_dir(env_name: str, default: Path) -> Path:
    override = os.environ.get(env_name)
    return Path(override).expanduser().resolve() if override else default


DATA_DIR = _resolved_dir("JOB_MINER_DATA_DIR", REPO_ROOT / "data")
VAULT_DIR = _resolved_dir("JOB_MINER_VAULT_DIR", REPO_ROOT / "obsidian_vault")
RATE_LIMIT_FILE = DATA_DIR / "rate_limit.json"
SETTINGS_FILE = DATA_DIR / "settings.json"


# ---------------------------------------------------------------------------
# Rate limiter (daily parse cap, persisted across restarts)
# ---------------------------------------------------------------------------

# Hard cap on how many vacancies a single day can land in the vault via
# the API. Prevents an accidental infinite-loop autopilot from filling
# the vault with junk. Counter resets at midnight local time.
DAILY_PARSE_CAP = _env_int("JOB_MINER_DAILY_CAP", 600)


def _today() -> str:
    return datetime.date.today().isoformat()


def _load_rate_state() -> dict:
    if not RATE_LIMIT_FILE.exists():
        return {"date": _today(), "parsed": 0}
    try:
        data = json.loads(RATE_LIMIT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"date": _today(), "parsed": 0}
    if data.get("date") != _today():
        return {"date": _today(), "parsed": 0}
    data.setdefault("parsed", 0)
    return data


def _save_rate_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RATE_LIMIT_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def parsed_today() -> int:
    return _load_rate_state()["parsed"]


def remaining_today() -> int:
    return max(0, effective_cap() - parsed_today())


def register_parse() -> int:
    """Increment the daily parsed counter. Returns new count."""
    state = _load_rate_state()
    state["parsed"] += 1
    _save_rate_state(state)
    return state["parsed"]


def can_parse_more() -> bool:
    return parsed_today() < effective_cap()


# ---------------------------------------------------------------------------
# User settings (autopilot mode, delays, daily cap)
# ---------------------------------------------------------------------------
#
# The plugin ships with three presets — "stealth" (conservative delays,
# low ban risk), "regular" (current default), "fast" (aggressive, short
# bursts only). Users can also hand-tune every delay and flip
# randomisation off via the sidebar settings panel; once they touch a
# single value the mode flips to "custom".
#
# Settings are stored runtime-only in `data/settings.json` (gitignored
# alongside rate_limit.json) and read fresh on every `/api/parse`,
# `/api/dashboard`, and on every autopilot run. Missing file = defaults.

_UNLIMITED = 10**9  # treated as "no cap" by callers; arbitrary large int


def _default_settings() -> dict:
    """Defaults — read DAILY_PARSE_CAP at call time so tests that
    monkeypatch the env-derived cap see the patched value."""
    return {
        "mode":             "regular",
        "daily_cap":        DAILY_PARSE_CAP,
        "randomize_delays": True,
        "delays_ms": {
            "click_min":           2500, "click_max":           5000,
            "between_saves_min":   8000, "between_saves_max":  20000,
            "page_transition_min": 4000, "page_transition_max": 9000,
        },
    }


PRESETS = {
    "stealth": {
        "daily_cap":        400,
        "randomize_delays": True,
        "delays_ms": {
            "click_min":           4000, "click_max":           8000,
            "between_saves_min":  20000, "between_saves_max":  45000,
            "page_transition_min":10000, "page_transition_max":20000,
        },
    },
    "regular": {
        "daily_cap":        600,
        "randomize_delays": True,
        "delays_ms": {
            "click_min":           2500, "click_max":           5000,
            "between_saves_min":   8000, "between_saves_max":  20000,
            "page_transition_min": 4000, "page_transition_max": 9000,
        },
    },
    "fast": {
        "daily_cap":        1500,
        "randomize_delays": False,
        "delays_ms": {
            "click_min":            500, "click_max":           1500,
            "between_saves_min":   2000, "between_saves_max":   5000,
            "page_transition_min": 1000, "page_transition_max": 3000,
        },
    },
}


_DELAY_PAIRS = (
    ("click_min", "click_max"),
    ("between_saves_min", "between_saves_max"),
    ("page_transition_min", "page_transition_max"),
)


def load_settings() -> dict:
    """Current effective settings, merged over defaults. Never raises."""
    defaults = _default_settings()
    if not SETTINGS_FILE.exists():
        return defaults
    try:
        stored = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return defaults
    if not isinstance(stored, dict):
        return defaults
    merged = dict(defaults)
    for key, val in stored.items():
        if key == "delays_ms" and isinstance(val, dict):
            merged_delays = dict(defaults["delays_ms"])
            merged_delays.update({k: v for k, v in val.items() if isinstance(v, int)})
            merged["delays_ms"] = merged_delays
        else:
            merged[key] = val
    return merged


def _validate_settings(s: dict) -> None:
    """Raise ValueError on invalid settings. Called before write."""
    mode = s.get("mode")
    if mode not in ("stealth", "regular", "fast", "custom"):
        raise ValueError(f"mode must be stealth|regular|fast|custom, got {mode!r}")
    cap = s.get("daily_cap")
    if cap is not None and not (isinstance(cap, int) and 1 <= cap <= 9999):
        raise ValueError("daily_cap must be null or integer 1..9999")
    if not isinstance(s.get("randomize_delays"), bool):
        raise ValueError("randomize_delays must be boolean")
    dm = s.get("delays_ms")
    if not isinstance(dm, dict):
        raise ValueError("delays_ms must be an object")
    for mn_k, mx_k in _DELAY_PAIRS:
        mn_v, mx_v = dm.get(mn_k), dm.get(mx_k)
        if not (isinstance(mn_v, int) and isinstance(mx_v, int)):
            raise ValueError(f"{mn_k}/{mx_k} must be integers")
        if mn_v < 100 or mx_v > 120000:
            raise ValueError(f"{mn_k}/{mx_k} must be in 100..120000 ms")
        if mn_v > mx_v:
            raise ValueError(f"{mn_k} must be <= {mx_k}")


def save_settings(partial: dict) -> dict:
    """Merge partial into current, validate, persist, return full state.
    Raises ValueError on invalid input."""
    if not isinstance(partial, dict):
        raise ValueError("settings payload must be an object")
    current = load_settings()
    merged = dict(current)
    for key, val in partial.items():
        if key == "delays_ms" and isinstance(val, dict):
            merged_delays = dict(current["delays_ms"])
            merged_delays.update(val)
            merged["delays_ms"] = merged_delays
        else:
            merged[key] = val
    _validate_settings(merged)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return merged


def apply_preset(name: str) -> dict:
    """Overwrite settings with a named preset, leaving `mode` = name."""
    if name not in PRESETS:
        raise ValueError(f"unknown preset {name!r}; expected one of {list(PRESETS)}")
    preset = PRESETS[name]
    payload = {"mode": name, **preset}
    return save_settings(payload)


def effective_cap() -> int:
    """Daily cap that /api/parse enforces right now. None in settings = no cap."""
    cap = load_settings().get("daily_cap")
    return _UNLIMITED if cap is None else cap
