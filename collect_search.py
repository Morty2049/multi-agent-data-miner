"""
collect_search.py — Collect LinkedIn job URLs from a /jobs/search/ URL via CDP.

Connects to an already-running Chrome (e.g. Antigravity IDE's bundled Chrome)
over CDP, so we reuse an existing logged-in LinkedIn session without launching
a new browser or risking the main account.

Pagination is done by appending &start=0,25,50,... to the search URL.
Scroll + extract logic mirrors collect_queue.py.

Usage:
    venv/bin/python collect_search.py "<search_url>" [--pages N] [--cdp URL] [--output FILE]

Example:
    venv/bin/python collect_search.py \
        "https://www.linkedin.com/jobs/search/?f_WT=1%2C2&geoId=90010352&sortBy=R" \
        --pages 40
"""
import asyncio
import datetime
import json
import os
import random
import re
import sys
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from playwright.async_api import async_playwright

from config import (
    COLLECT_DELAY_MAX,
    COLLECT_DELAY_MIN,
    LinkedInBanned,
    assert_not_banned,
)

DATA_DIR = os.path.abspath("data")
QUEUE_FILE = os.path.join(DATA_DIR, "job_queue_prod.json")
PARSED_FILE = os.path.join(DATA_DIR, "job_queue_prod_parsed.json")
LOG_FILE = os.path.join(DATA_DIR, "collect_log.json")

DELAY_MIN = COLLECT_DELAY_MIN
DELAY_MAX = COLLECT_DELAY_MAX
PAGE_LOAD_WAIT = 5
MAX_SCROLL_ATTEMPTS = 18
SCROLL_STEP = 600
PAGE_SIZE = 25  # /jobs/search/ paginates in 25s


EXTRACT_JOB_IDS_JS = r"""
() => {
    const ids = new Set();
    for (const a of document.querySelectorAll('a[href*="/jobs/view/"]')) {
        const m = a.href.match(/\/jobs\/view\/(\d+)/);
        if (m) ids.add(m[1]);
    }
    for (const el of document.querySelectorAll('[data-job-id]')) {
        const id = el.getAttribute('data-job-id');
        if (id && /^\d+$/.test(id)) ids.add(id);
    }
    for (const a of document.querySelectorAll('a[href*="currentJobId="]')) {
        const m = a.href.match(/currentJobId=(\d+)/);
        if (m) ids.add(m[1]);
    }
    for (const el of document.querySelectorAll('[data-occludable-job-id]')) {
        const id = el.getAttribute('data-occludable-job-id');
        if (id && /^\d+$/.test(id)) ids.add(id);
    }
    return Array.from(ids);
}
"""

SCROLL_JOB_LIST_JS = r"""
(scrollBy) => {
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
                scrolled: true, selector: sel,
                scrollTop: el.scrollTop, scrollHeight: el.scrollHeight,
                clientHeight: el.clientHeight,
                atBottom: (el.scrollTop + el.clientHeight) >= (el.scrollHeight - 50),
            };
        }
    }
    window.scrollBy(0, scrollBy);
    return {
        scrolled: true, selector: 'window',
        scrollTop: window.scrollY, scrollHeight: document.body.scrollHeight,
        clientHeight: window.innerHeight,
        atBottom: (window.scrollY + window.innerHeight) >= (document.body.scrollHeight - 50),
    };
}
"""


def load_json(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def with_start(url: str, start: int) -> str:
    parts = urlparse(url)
    qs = dict(parse_qsl(parts.query, keep_blank_values=True))
    qs["start"] = str(start)
    qs.pop("currentJobId", None)
    return urlunparse(parts._replace(query=urlencode(qs)))


def job_id_from_url(url: str) -> str:
    m = re.search(r"/jobs/view/(\d+)", url)
    return m.group(1) if m else ""


async def collect_search(page, search_url: str, pages: int) -> list[str]:
    all_ids: set[str] = set()
    print(f"\n{'='*60}")
    print(f"🔍 Collecting /jobs/search/ ({pages} pages × {PAGE_SIZE})")
    print(f"   {search_url}")
    print(f"{'='*60}")

    consecutive_empty = 0

    for page_num in range(pages):
        start = page_num * PAGE_SIZE
        url = with_start(search_url, start)
        print(f"\n📄 Page {page_num + 1}/{pages} (start={start})")

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(PAGE_LOAD_WAIT)
            await assert_not_banned(page)

            ids_before = await page.evaluate(EXTRACT_JOB_IDS_JS)
            page_ids = set(ids_before)
            print(f"   Initial: {len(page_ids)} cards")

            for scroll_i in range(MAX_SCROLL_ATTEMPTS):
                scroll_info = await page.evaluate(SCROLL_JOB_LIST_JS, SCROLL_STEP)
                await asyncio.sleep(1.5)
                ids_now = await page.evaluate(EXTRACT_JOB_IDS_JS)
                new_in_scroll = set(ids_now) - page_ids
                page_ids.update(ids_now)
                if new_in_scroll:
                    print(f"   Scroll {scroll_i+1}: +{len(new_in_scroll)} "
                          f"({len(page_ids)} on page, via {scroll_info.get('selector','?')})")
                if scroll_info.get("atBottom", False):
                    await asyncio.sleep(2)
                    page_ids.update(await page.evaluate(EXTRACT_JOB_IDS_JS))
                    print(f"   Reached bottom ({len(page_ids)} cards)")
                    break

            new_ids = page_ids - all_ids
            all_ids.update(page_ids)
            print(f"   ✓ {len(page_ids)} on page, {len(new_ids)} new, {len(all_ids)} total")

            if len(new_ids) == 0:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    print(f"   ⚠️  Two empty pages in a row — stopping")
                    break
            else:
                consecutive_empty = 0

        except LinkedInBanned as e:
            print(f"   🛑 LinkedIn ban/checkpoint — halting: {e}")
            break
        except Exception as e:
            print(f"   ❌ Error: {e}")
            break

        delay = random.uniform(DELAY_MIN, DELAY_MAX)
        print(f"   ⏳ Waiting {delay:.1f}s...")
        await asyncio.sleep(delay)

    urls = [f"https://www.linkedin.com/jobs/view/{jid}/" for jid in sorted(all_ids)]
    print(f"\n✅ Collected {len(urls)} job URLs")
    return urls


async def main(search_url: str, pages: int, cdp_url: str, output: str):
    queue_file = output or QUEUE_FILE
    queue = load_json(queue_file) if isinstance(load_json(queue_file), list) else []
    parsed = load_json(PARSED_FILE) if isinstance(load_json(PARSED_FILE), list) else []
    log = load_json(LOG_FILE) if isinstance(load_json(LOG_FILE), dict) else {}
    if not isinstance(log, dict):
        log = {}
    existing = set(queue) | set(parsed)
    today = datetime.datetime.now().strftime("%Y-%m-%d")

    print(f"📊 Current state:")
    print(f"   Queue: {len(queue)}")
    print(f"   Parsed: {len(parsed)}")
    print(f"   Known total: {len(existing)}")
    print(f"   CDP: {cdp_url}")

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
        try:
            urls = await collect_search(page, search_url, pages)
        finally:
            try:
                await page.close()
            except Exception:
                pass
            await browser.close()  # detaches CDP, doesn't kill the host browser

    for u in urls:
        jid = job_id_from_url(u)
        if jid and jid not in log:
            log[jid] = {"source": "search_pt_market", "collected_at": today}

    new_urls = [u for u in urls if u not in existing]
    new_urls = list(dict.fromkeys(new_urls))
    queue.extend(new_urls)
    save_json(queue_file, queue)
    save_json(LOG_FILE, log)

    print(f"\n{'='*60}")
    print(f"📋 RESULTS")
    print(f"   Collected: {len(urls)}")
    print(f"   New (deduped): {len(new_urls)}")
    print(f"   Queue size: {len(queue)} → {os.path.basename(queue_file)}")
    print(f"{'='*60}")


def parse_args(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    search_url = argv[0]
    pages = 40
    cdp_url = "http://localhost:9222"
    output = ""
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--pages":
            pages = int(argv[i + 1]); i += 2
        elif a.startswith("--pages="):
            pages = int(a.split("=", 1)[1]); i += 1
        elif a == "--cdp":
            cdp_url = argv[i + 1]; i += 2
        elif a.startswith("--cdp="):
            cdp_url = a.split("=", 1)[1]; i += 1
        elif a == "--output":
            output = argv[i + 1]; i += 2
        elif a.startswith("--output="):
            output = a.split("=", 1)[1]; i += 1
        else:
            print(f"Unknown arg: {a}"); sys.exit(1)
    return search_url, pages, cdp_url, output


if __name__ == "__main__":
    search_url, pages, cdp_url, output = parse_args(sys.argv[1:])
    asyncio.run(main(search_url, pages, cdp_url, output))
