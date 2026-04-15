"""
run_queue.py — Process LinkedIn job URLs from a queue file in batch.

Usage:
    venv/bin/python run_queue.py                          # uses data/job_queue_prod.json
    venv/bin/python run_queue.py data/job_queue.json      # custom queue file
    venv/bin/python run_queue.py --limit 10               # process only first 10

Moves successfully parsed URLs into *_parsed.json.
Failed URLs remain in the queue for retry.
Uses a SINGLE browser context for all jobs (fast!).

Safety layers (see config.py):
  • uses LINKEDIN_SESSION_DIR (palexe888 by default), never the main account
  • random 8–20 s delay between jobs (humanized)
  • hard daily parse cap (600 vacancies/day) persisted in data/rate_limit.json
  • exponential backoff on transient errors
  • immediate halt if a LinkedIn checkpoint / authwall is detected
"""
import asyncio
import json
import os
import sys
import time

from playwright.async_api import async_playwright

import config
from config import (
    DailyCapReached,
    LinkedInBanned,
    SESSION_DIR,
    USER_AGENT,
)
from parse_job import parse_job

QUEUE_FILE = "data/job_queue_prod.json"


def load_json(path: str) -> list:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []


def save_json(path: str, data: list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def _sleep_with_backoff(attempt: int) -> None:
    wait = config.backoff_seconds(attempt)
    print(f"  ⏳ backoff #{attempt}: sleeping {wait:.0f}s")
    await asyncio.sleep(wait)


async def run_queue(queue_file: str = QUEUE_FILE, limit: int = 0):
    """Process URLs from queue_file using a single shared browser context."""
    queue = load_json(queue_file)

    base, ext = os.path.splitext(queue_file)
    parsed_file = f"{base}_parsed{ext}"

    parsed = load_json(parsed_file)
    parsed_set = set(parsed)

    remaining = [url for url in queue if url not in parsed_set]

    # Respect daily cap — user-supplied limit still narrows further.
    daily_left = config.remaining_today()
    if daily_left <= 0:
        print(
            f"🛑 Daily parse cap reached ({config.DAILY_PARSE_CAP} vacancies "
            f"already parsed today). Try again tomorrow."
        )
        return
    if limit > 0:
        remaining = remaining[:limit]
    remaining = remaining[:daily_left]

    total = len(remaining)
    if total == 0:
        print("✅ Queue is empty or all URLs already parsed.")
        return

    avg_delay = (config.PARSE_DELAY_MIN + config.PARSE_DELAY_MAX) / 2
    est_sec = int(total * (avg_delay + 12))
    est_min = est_sec // 60

    print(f"📋 Queue: {total} jobs to process")
    print(f"📦 Parsed: {len(parsed)} already done → {os.path.basename(parsed_file)}")
    print(
        f"📊 Daily cap: {config.parsed_today()}/{config.DAILY_PARSE_CAP} used "
        f"— {daily_left} remaining"
    )
    print(
        f"⏱  Delay: {config.PARSE_DELAY_MIN:.0f}–{config.PARSE_DELAY_MAX:.0f}s "
        f"random between jobs"
    )
    print(f"⏳ Estimate: ~{est_min} min ({est_sec}s)")
    print(f"🔐 Session: {os.path.basename(SESSION_DIR)}")
    print("=" * 60)

    success = 0
    failed = 0
    failed_urls: list[str] = []
    backoff_attempt = 0
    start_time = time.time()
    stop_reason: str | None = None

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=True,
            user_agent=USER_AGENT,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            for i, url in enumerate(remaining, 1):
                elapsed = time.time() - start_time
                avg_per_job = elapsed / max(i - 1, 1)
                eta = avg_per_job * (total - i + 1)

                print(f"\n[{i}/{total}] (ETA: {int(eta)}s) {url}")

                try:
                    await parse_job(url, page=page)
                except LinkedInBanned as exc:
                    stop_reason = f"LinkedIn ban/checkpoint detected: {exc}"
                    print(f"  🛑 {stop_reason}")
                    failed += 1
                    failed_urls.append(url)
                    break
                except Exception as exc:
                    backoff_attempt += 1
                    print(f"  ❌ FAILED: {exc}")
                    failed += 1
                    failed_urls.append(url)
                    if backoff_attempt > config.BACKOFF_MAX_ATTEMPTS:
                        stop_reason = (
                            f"too many consecutive failures "
                            f"({backoff_attempt} > {config.BACKOFF_MAX_ATTEMPTS})"
                        )
                        print(f"  🛑 {stop_reason}")
                        break
                    await _sleep_with_backoff(backoff_attempt)
                    continue
                else:
                    backoff_attempt = 0  # reset on success

                    parsed.append(url)
                    parsed_set.add(url)
                    save_json(parsed_file, parsed)

                    queue = [u for u in queue if u != url]
                    save_json(queue_file, queue)

                    success += 1
                    new_count = config.register_parse()
                    if new_count >= config.DAILY_PARSE_CAP:
                        stop_reason = (
                            f"daily cap reached ({new_count}/"
                            f"{config.DAILY_PARSE_CAP})"
                        )
                        print(f"  🛑 {stop_reason}")
                        break

                if i < total:
                    delay = config.random_delay(
                        config.PARSE_DELAY_MIN, config.PARSE_DELAY_MAX
                    )
                    print(f"  ⏳ waiting {delay:.1f}s...")
                    await asyncio.sleep(delay)
        finally:
            await ctx.close()

    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"✅ Done in {int(elapsed)}s: {success}/{total} succeeded, {failed} failed")
    print(
        f"📊 Daily count: {config.parsed_today()}/{config.DAILY_PARSE_CAP}"
    )
    if stop_reason:
        print(f"🛑 Stopped early: {stop_reason}")
    if failed_urls:
        print("❌ Failed URLs (still in queue):")
        for u in failed_urls:
            print(f"   {u}")


if __name__ == "__main__":
    queue_file = QUEUE_FILE
    limit = 0

    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
        elif arg.startswith("--limit="):
            limit = int(arg.split("=")[1])
        elif arg.endswith(".json"):
            queue_file = arg

    try:
        asyncio.run(run_queue(queue_file, limit))
    except DailyCapReached as exc:
        print(f"🛑 {exc}")
        sys.exit(0)
