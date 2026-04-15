"""
config.py — central configuration, rate limiter, and ban-detector.

All LinkedIn-facing scripts import from here so we have ONE place to change:
- which account (session dir) is used
- how aggressive we are (delays, daily cap)
- what counts as a "LinkedIn is onto us" signal

Reads optional `.env` file in the repo root (simple key=value parser, no
external dependency). Environment variables override .env values.
"""
from __future__ import annotations

import datetime
import json
import os
import random
from pathlib import Path


# ---------------------------------------------------------------------------
# .env loader (no third-party dep)
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
        # Process env wins — never override an already-set variable.
        os.environ.setdefault(key, value)


_load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Account / session
# ---------------------------------------------------------------------------

# Which LinkedIn profile dir to use. Defaults to the "market" account
# (palexe888) — the only one we are allowed to touch.
SESSION_DIR_NAME = _env("LINKEDIN_SESSION_DIR", "linkedin_session_market")
SESSION_DIR = str(REPO_ROOT / SESSION_DIR_NAME)

# Account email — used only for informational prints in login_market.py.
# Not a secret, but we keep it out of the source.
LINKEDIN_ACCOUNT_EMAIL = _env("LINKEDIN_ACCOUNT_EMAIL", "")

# Path to a real Chrome binary (needed for patchright stealth login).
CHROME_PATH = _env(
    "CHROME_PATH",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

USER_AGENT = _env(
    "LINKEDIN_USER_AGENT",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = REPO_ROOT / "data"
VAULT_DIR = REPO_ROOT / "obsidian_vault"
RATE_LIMIT_FILE = DATA_DIR / "rate_limit.json"


# ---------------------------------------------------------------------------
# Anti-ban pacing
# ---------------------------------------------------------------------------

# Per-page delay while browsing lists (collect_*).
COLLECT_DELAY_MIN = _env_float("LINKEDIN_COLLECT_DELAY_MIN", 3.0)
COLLECT_DELAY_MAX = _env_float("LINKEDIN_COLLECT_DELAY_MAX", 8.0)

# Per-job delay inside run_queue.py. Random human-ish pacing, no more fixed 3s.
PARSE_DELAY_MIN = _env_float("LINKEDIN_PARSE_DELAY_MIN", 8.0)
PARSE_DELAY_MAX = _env_float("LINKEDIN_PARSE_DELAY_MAX", 20.0)

# Hard daily cap on successfully parsed vacancies. Counter persists in
# data/rate_limit.json and resets at midnight local time.
DAILY_PARSE_CAP = _env_int("LINKEDIN_DAILY_PARSE_CAP", 600)

# Exponential backoff on transient errors / suspicious pages.
BACKOFF_BASE_SEC = _env_float("LINKEDIN_BACKOFF_BASE", 30.0)
BACKOFF_MAX_SEC = _env_float("LINKEDIN_BACKOFF_MAX", 600.0)
BACKOFF_MAX_ATTEMPTS = _env_int("LINKEDIN_BACKOFF_MAX_ATTEMPTS", 5)


def random_delay(lo: float, hi: float) -> float:
    return random.uniform(lo, hi)


def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with jitter. `attempt` is 1-indexed."""
    base = BACKOFF_BASE_SEC * (2 ** (attempt - 1))
    capped = min(base, BACKOFF_MAX_SEC)
    jitter = random.uniform(0.75, 1.25)
    return round(capped * jitter, 1)


# ---------------------------------------------------------------------------
# Rate limiter (daily parse cap, persisted)
# ---------------------------------------------------------------------------


def _today() -> str:
    return datetime.date.today().isoformat()


def _load_rate_state() -> dict:
    if not RATE_LIMIT_FILE.exists():
        return {"date": _today(), "parsed": 0, "collected": 0}
    try:
        data = json.loads(RATE_LIMIT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"date": _today(), "parsed": 0, "collected": 0}
    if data.get("date") != _today():
        return {"date": _today(), "parsed": 0, "collected": 0}
    data.setdefault("parsed", 0)
    data.setdefault("collected", 0)
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


class DailyCapReached(RuntimeError):
    """Raised when the daily parse cap is hit — stops the batch cleanly."""


# ---------------------------------------------------------------------------
# Ban / auth-wall detection
# ---------------------------------------------------------------------------

# URL fragments that mean LinkedIn kicked us out / wants a challenge.
BAN_URL_PATTERNS = (
    "/checkpoint/",
    "/authwall",
    "/uas/login",
    "/login?",
    "/security/",
)

# Case-insensitive substrings that appear on ban / verify pages.
BAN_TEXT_PATTERNS = (
    "unusual activity",
    "security verification",
    "let's do a quick security check",
    "please sign in",
    "we restrict",
    "your account has been temporarily",
    "we've detected some unusual activity",
)


class LinkedInBanned(RuntimeError):
    """Raised when we detect a checkpoint / authwall / rate-limit screen."""


async def detect_ban(page) -> str | None:
    """Return a reason string if the page looks like a ban/auth-wall, else None."""
    try:
        url = page.url or ""
    except Exception:
        url = ""
    for pat in BAN_URL_PATTERNS:
        if pat in url:
            return f"ban url match: {pat} (url={url})"

    try:
        title = (await page.title()) or ""
    except Exception:
        title = ""
    low_title = title.lower()
    if "security" in low_title and "verification" in low_title:
        return f"ban title: {title}"

    try:
        body = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:
        body = ""
    low_body = (body or "")[:4000].lower()
    for pat in BAN_TEXT_PATTERNS:
        if pat in low_body:
            return f"ban text: {pat!r}"

    return None


async def assert_not_banned(page) -> None:
    reason = await detect_ban(page)
    if reason:
        raise LinkedInBanned(reason)
