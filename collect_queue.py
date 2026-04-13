"""
collect_queue.py — Collect LinkedIn job URLs into the processing queue.

TIER 1: Recommended jobs with pagination
    /jobs/collections/recommended/?start=0,24,48...

TIER 2: Similar jobs from hand-picked seeds
    /jobs/collections/similar-jobs/?currentJobId=X&referenceJobId=X

Usage:
    venv/bin/python collect_queue.py --tier1 --pages 10
    venv/bin/python collect_queue.py --tier2
    venv/bin/python collect_queue.py --all --pages 10
    venv/bin/python collect_queue.py --help
"""
import asyncio
import json
import os
import random
import re
import sys
import time
import datetime

from playwright.async_api import async_playwright

SESSION_DIR = os.path.abspath("linkedin_session")
DATA_DIR = os.path.abspath("data")
QUEUE_FILE = os.path.join(DATA_DIR, "job_queue_prod.json")
PARSED_FILE = os.path.join(DATA_DIR, "job_queue_prod_parsed.json")
LOG_FILE = os.path.join(DATA_DIR, "collect_log.json")
SEEDS_FILE = os.path.join(DATA_DIR, "tier2_seeds.json")

RECOMMENDED_URL = "https://www.linkedin.com/jobs/collections/recommended/"
SIMILAR_URL_TPL = "https://www.linkedin.com/jobs/collections/similar-jobs/?currentJobId={job_id}&referenceJobId={job_id}"

# Humanized delays (seconds)
DELAY_MIN = 3
DELAY_MAX = 8
PAGE_LOAD_WAIT = 5  # seconds after page load


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_json(path: str) -> list | dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_log() -> dict:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_log(log: dict):
    save_json(LOG_FILE, log)


def job_id_from_url(url: str) -> str:
    m = re.search(r"/jobs/view/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"currentJobId=(\d+)", url)
    return m.group(1) if m else ""


def humanized_delay():
    """Random sleep to mimic human behavior."""
    delay = random.uniform(DELAY_MIN, DELAY_MAX)
    time.sleep(0)  # yield
    return delay


# ---------------------------------------------------------------------------
# JS extractors
# ---------------------------------------------------------------------------

EXTRACT_JOB_IDS_JS = r"""
() => {
    const ids = new Set();
    
    // Method 1: links with /jobs/view/
    const links = document.querySelectorAll('a[href*="/jobs/view/"]');
    for (const a of links) {
        const m = a.href.match(/\/jobs\/view\/(\d+)/);
        if (m) ids.add(m[1]);
    }
    
    // Method 2: data attributes with job IDs
    const dataEls = document.querySelectorAll('[data-job-id]');
    for (const el of dataEls) {
        const id = el.getAttribute('data-job-id');
        if (id && /^\d+$/.test(id)) ids.add(id);
    }
    
    // Method 3: currentJobId in link hrefs
    const allLinks = document.querySelectorAll('a[href*="currentJobId="]');
    for (const a of allLinks) {
        const m = a.href.match(/currentJobId=(\d+)/);
        if (m) ids.add(m[1]);
    }
    
    // Method 4: li elements with data-occludable-job-id (LinkedIn's virtual list)
    const occludable = document.querySelectorAll('[data-occludable-job-id]');
    for (const el of occludable) {
        const id = el.getAttribute('data-occludable-job-id');
        if (id && /^\d+$/.test(id)) ids.add(id);
    }
    
    return Array.from(ids);
}
"""

# JS to find and scroll the job list container
SCROLL_JOB_LIST_JS = r"""
(scrollBy) => {
    // LinkedIn uses a scrollable container for the job list panel
    // Try multiple selectors — LinkedIn changes class names
    const selectors = [
        '.scaffold-layout__list .jobs-search-results-list',
        '.scaffold-layout__list > div',
        '.scaffold-layout__list',
        '.jobs-search-results-list',
        '[class*="jobs-search-results"]',
        'div.scaffold-layout__list-detail-inner',
    ];
    
    for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el && el.scrollHeight > el.clientHeight) {
            el.scrollBy(0, scrollBy);
            return {
                scrolled: true,
                selector: sel,
                scrollTop: el.scrollTop,
                scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
                atBottom: (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 50)
            };
        }
    }
    
    // Fallback: scroll the main window
    window.scrollBy(0, scrollBy);
    return {
        scrolled: true,
        selector: 'window',
        scrollTop: window.scrollY,
        scrollHeight: document.body.scrollHeight,
        clientHeight: window.innerHeight,
        atBottom: (window.scrollY + window.innerHeight) >= (document.body.scrollHeight - 50)
    };
}
"""

MAX_SCROLL_ATTEMPTS = 15  # max scroll iterations per page
SCROLL_STEP = 600  # pixels per scroll increment


# ---------------------------------------------------------------------------
# TIER 1: Recommended Jobs
# ---------------------------------------------------------------------------

async def collect_tier1(page, pages: int = 10) -> list[str]:
    """Collect job URLs from LinkedIn Recommended Jobs with pagination.
    
    Scrolls the job list container incrementally to trigger lazy-loading
    of all ~24 cards per page.
    """
    all_ids = set()

    print(f"\n{'='*60}")
    print(f"🔍 TIER 1: Collecting Recommended Jobs ({pages} pages)")
    print(f"{'='*60}")

    for page_num in range(pages):
        start = page_num * 24
        url = f"{RECOMMENDED_URL}?start={start}" if start > 0 else RECOMMENDED_URL

        print(f"\n📄 Page {page_num + 1}/{pages} (start={start})")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(PAGE_LOAD_WAIT)

            # Initial extraction before scrolling
            ids_before = await page.evaluate(EXTRACT_JOB_IDS_JS)
            page_ids = set(ids_before)
            print(f"   Initial: {len(page_ids)} cards visible")

            # Incrementally scroll the job list container
            for scroll_i in range(MAX_SCROLL_ATTEMPTS):
                scroll_info = await page.evaluate(SCROLL_JOB_LIST_JS, SCROLL_STEP)
                await asyncio.sleep(1.5)  # wait for lazy-load

                ids_now = await page.evaluate(EXTRACT_JOB_IDS_JS)
                new_in_scroll = set(ids_now) - page_ids
                page_ids.update(ids_now)

                if new_in_scroll:
                    print(f"   Scroll {scroll_i+1}: +{len(new_in_scroll)} cards "
                          f"({len(page_ids)} total, via {scroll_info.get('selector', '?')})")

                # Stop if at bottom and no new cards in last 2 scrolls
                if scroll_info.get("atBottom", False):
                    # One more wait and extract in case of late loading
                    await asyncio.sleep(2)
                    ids_final = await page.evaluate(EXTRACT_JOB_IDS_JS)
                    page_ids.update(ids_final)
                    print(f"   Reached bottom of list ({len(page_ids)} cards on page)")
                    break

            new_ids = page_ids - all_ids
            all_ids.update(page_ids)
            print(f"   ✓ Page result: {len(page_ids)} IDs ({len(new_ids)} new, {len(all_ids)} total)")

            if len(new_ids) == 0:
                print(f"   ⚠️ No new jobs on this page — stopping pagination")
                break

        except Exception as e:
            print(f"   ❌ Error: {e}")
            break

        # Humanized delay between pages
        delay = humanized_delay()
        print(f"   ⏳ Waiting {delay:.1f}s...")
        await asyncio.sleep(delay)

    urls = [f"https://www.linkedin.com/jobs/view/{jid}/" for jid in sorted(all_ids)]
    print(f"\n✅ TIER 1 total: {len(urls)} job URLs collected")
    return urls


# ---------------------------------------------------------------------------
# TIER 2: Similar Jobs
# ---------------------------------------------------------------------------

async def collect_tier2(page) -> list[str]:
    """Collect job URLs from similar-jobs pages using seeds file."""
    seeds = load_json(SEEDS_FILE)
    if not seeds:
        print("\n⚠️ No seeds found in data/tier2_seeds.json — skipping TIER 2")
        return []

    all_ids = set()

    print(f"\n{'='*60}")
    print(f"🔗 TIER 2: Collecting Similar Jobs ({len(seeds)} seeds)")
    print(f"{'='*60}")

    for i, seed_url in enumerate(seeds, 1):
        seed_id = job_id_from_url(seed_url)
        if not seed_id:
            print(f"\n[{i}/{len(seeds)}] ⚠️ Cannot extract job ID from: {seed_url}")
            continue

        similar_url = SIMILAR_URL_TPL.format(job_id=seed_id)
        print(f"\n[{i}/{len(seeds)}] Seed: {seed_id}")
        print(f"   URL: {similar_url}")

        try:
            await page.goto(similar_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(PAGE_LOAD_WAIT)

            # Initial extraction
            ids_before = await page.evaluate(EXTRACT_JOB_IDS_JS)
            page_ids = set(ids_before)

            # Scroll the job list container incrementally
            for scroll_i in range(MAX_SCROLL_ATTEMPTS):
                scroll_info = await page.evaluate(SCROLL_JOB_LIST_JS, SCROLL_STEP)
                await asyncio.sleep(1.5)

                ids_now = await page.evaluate(EXTRACT_JOB_IDS_JS)
                page_ids.update(ids_now)

                if scroll_info.get("atBottom", False):
                    await asyncio.sleep(2)
                    ids_final = await page.evaluate(EXTRACT_JOB_IDS_JS)
                    page_ids.update(ids_final)
                    break

            # Remove the seed job itself
            page_ids.discard(seed_id)
            new_ids = page_ids - all_ids
            all_ids.update(page_ids)

            print(f"   Found {len(page_ids)} similar jobs ({len(new_ids)} new)")

        except Exception as e:
            print(f"   ❌ Error: {e}")

        # Humanized delay
        if i < len(seeds):
            delay = humanized_delay()
            print(f"   ⏳ Waiting {delay:.1f}s...")
            await asyncio.sleep(delay)

    urls = [f"https://www.linkedin.com/jobs/view/{jid}/" for jid in sorted(all_ids)]
    print(f"\n✅ TIER 2 total: {len(urls)} job URLs collected")
    return urls


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

async def collect(tier1: bool = False, tier2: bool = False, pages: int = 10,
                  output: str = ""):
    """Collect job URLs and merge into the queue."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # Load existing state
    queue = load_json(output or QUEUE_FILE) if isinstance(load_json(output or QUEUE_FILE), list) else []
    parsed = load_json(PARSED_FILE) if isinstance(load_json(PARSED_FILE), list) else []
    log = load_log()

    existing_set = set(queue) | set(parsed)
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    print(f"📊 Current state:")
    print(f"   Queue: {len(queue)} URLs")
    print(f"   Parsed: {len(parsed)} URLs")
    print(f"   Known total: {len(existing_set)} URLs")

    collected_urls = []

    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR,
            headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        try:
            if tier1:
                urls = await collect_tier1(page, pages=pages)
                for url in urls:
                    jid = job_id_from_url(url)
                    if jid and jid not in log:
                        log[jid] = {
                            "source": "tier1_recommended",
                            "collected_at": today,
                        }
                collected_urls.extend(urls)

            if tier2:
                urls = await collect_tier2(page)
                for url in urls:
                    jid = job_id_from_url(url)
                    if jid and jid not in log:
                        log[jid] = {
                            "source": "tier2_similar",
                            "collected_at": today,
                        }
                collected_urls.extend(urls)
        finally:
            await ctx.close()

    # Deduplicate against existing queue + parsed
    new_urls = [url for url in collected_urls if url not in existing_set]
    new_urls = list(dict.fromkeys(new_urls))  # preserve order, remove dupes

    # Merge into queue
    target_file = output or QUEUE_FILE
    queue.extend(new_urls)
    save_json(target_file, queue)
    save_log(log)

    print(f"\n{'='*60}")
    print(f"📋 RESULTS:")
    print(f"   Collected: {len(collected_urls)} URLs total")
    print(f"   New (deduplicated): {len(new_urls)} URLs")
    print(f"   Queue size: {len(queue)} → {os.path.basename(target_file)}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_help():
    print("""
collect_queue.py — Collect LinkedIn job URLs into the processing queue.

Usage:
    venv/bin/python collect_queue.py --tier1 [--pages N]    Recommended jobs
    venv/bin/python collect_queue.py --tier2                 Similar jobs (from seeds)
    venv/bin/python collect_queue.py --all [--pages N]       Both tiers
    venv/bin/python collect_queue.py --help                  This message

Options:
    --tier1         Collect from Recommended Jobs feed
    --tier2         Collect similar jobs from data/tier2_seeds.json
    --all           Run both TIER 1 and TIER 2
    --pages N       Number of recommended pages to crawl (default: 10)
    --output FILE   Custom output queue file (default: data/job_queue_prod.json)
    --help          Show this help message

Examples:
    venv/bin/python collect_queue.py --tier1 --pages 5
    venv/bin/python collect_queue.py --tier2
    venv/bin/python collect_queue.py --all --pages 15 --output data/custom_queue.json
""")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--help" in args or "-h" in args or not args:
        print_help()
        sys.exit(0)

    tier1 = "--tier1" in args or "--all" in args
    tier2 = "--tier2" in args or "--all" in args
    pages = 10
    output = ""

    for i, arg in enumerate(args):
        if arg == "--pages" and i + 1 < len(args):
            pages = int(args[i + 1])
        elif arg.startswith("--pages="):
            pages = int(arg.split("=")[1])
        elif arg == "--output" and i + 1 < len(args):
            output = args[i + 1]
        elif arg.startswith("--output="):
            output = arg.split("=", 1)[1]

    if not tier1 and not tier2:
        print("❌ Specify --tier1, --tier2, or --all")
        sys.exit(1)

    asyncio.run(collect(tier1=tier1, tier2=tier2, pages=pages, output=output))
