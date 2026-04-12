"""
run_queue.py — Process LinkedIn job URLs from a queue file in batch.

Usage:
    venv/bin/python run_queue.py                          # uses data/job_queue_prod.json
    venv/bin/python run_queue.py data/job_queue.json      # custom queue file
    venv/bin/python run_queue.py --limit 10               # process only first 10

Moves successfully parsed URLs into *_parsed.json.
Failed URLs remain in the queue for retry.
Uses a SINGLE browser context for all jobs (fast!).
"""
import asyncio
import json
import os
import sys
import time

from playwright.async_api import async_playwright
from parse_job import parse_job, SESSION_DIR

QUEUE_FILE = "data/job_queue_prod.json"
DELAY_BETWEEN_JOBS = 3  # seconds — avoid LinkedIn rate-limiting


def load_json(path: str) -> list:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []


def save_json(path: str, data: list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def run_queue(queue_file: str = QUEUE_FILE, limit: int = 0):
    """Process URLs from queue_file using a single shared browser context."""
    queue = load_json(queue_file)
    
    # Derive parsed filename: job_queue_prod.json → job_queue_prod_parsed.json
    base, ext = os.path.splitext(queue_file)
    parsed_file = f"{base}_parsed{ext}"
    
    parsed = load_json(parsed_file)
    parsed_set = set(parsed)
    
    # Filter out already-parsed URLs
    remaining = [url for url in queue if url not in parsed_set]
    
    if limit > 0:
        remaining = remaining[:limit]
    
    total = len(remaining)
    if total == 0:
        print("✅ Queue is empty or all URLs already parsed.")
        return
    
    est_sec = total * (DELAY_BETWEEN_JOBS + 12)
    est_min = est_sec // 60
    
    print(f"📋 Queue: {total} jobs to process")
    print(f"📦 Parsed: {len(parsed)} already done → {os.path.basename(parsed_file)}")
    print(f"⏱  Delay: {DELAY_BETWEEN_JOBS}s between jobs")
    print(f"⏳ Estimate: ~{est_min} min ({est_sec}s)")
    print("=" * 60)
    
    success = 0
    failed = 0
    failed_urls = []
    start_time = time.time()
    
    # Open ONE browser context for the entire batch
    async with async_playwright() as pw:
        ctx = await pw.chromium.launch_persistent_context(
            user_data_dir=SESSION_DIR, headless=True,
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        for i, url in enumerate(remaining, 1):
            elapsed = time.time() - start_time
            avg_per_job = elapsed / max(i - 1, 1)
            eta = avg_per_job * (total - i + 1)
            
            print(f"\n[{i}/{total}] (ETA: {int(eta)}s) {url}")
            try:
                await parse_job(url, page=page)
                
                # Mark as parsed
                parsed.append(url)
                parsed_set.add(url)
                save_json(parsed_file, parsed)
                
                # Remove from queue
                queue = [u for u in queue if u != url]
                save_json(queue_file, queue)
                
                success += 1
                
            except Exception as e:
                print(f"  ❌ FAILED: {e}")
                failed += 1
                failed_urls.append(url)
            
            # Delay before next job
            if i < total:
                await asyncio.sleep(DELAY_BETWEEN_JOBS)
        
        await ctx.close()
    
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(f"✅ Done in {int(elapsed)}s: {success}/{total} succeeded, {failed} failed")
    if failed_urls:
        print(f"❌ Failed URLs (still in queue):")
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
    
    asyncio.run(run_queue(queue_file, limit))
