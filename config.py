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
    return max(0, DAILY_PARSE_CAP - parsed_today())


def register_parse() -> int:
    """Increment the daily parsed counter. Returns new count."""
    state = _load_rate_state()
    state["parsed"] += 1
    _save_rate_state(state)
    return state["parsed"]


def can_parse_more() -> bool:
    return parsed_today() < DAILY_PARSE_CAP
