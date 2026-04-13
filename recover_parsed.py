"""
recover_parsed.py — Rebuild data/job_queue_prod_parsed.json from existing vault.

Scans obsidian_vault/Vacancies/*.md files, extracts job IDs from filenames
and frontmatter, and generates the parsed-URLs list so that run_queue.py
and collect_queue.py know which jobs are already processed.

Usage:
    venv/bin/python recover_parsed.py
"""
import json
import os
import re
import datetime

VAULT_VACANCIES = os.path.abspath("obsidian_vault/Vacancies")
DATA_DIR = os.path.abspath("data")
PARSED_FILE = os.path.join(DATA_DIR, "job_queue_prod_parsed.json")
LOG_FILE = os.path.join(DATA_DIR, "collect_log.json")


def extract_job_id_from_filename(filename: str) -> str:
    """Extract job ID from filename like Company_-_Title_(4337768696).md"""
    m = re.search(r"\((\d{8,})\)", filename)
    return m.group(1) if m else ""


def extract_job_id_from_frontmatter(filepath: str) -> str:
    """Read the frontmatter job_id field as a fallback."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            in_frontmatter = False
            for line in f:
                if line.strip() == "---":
                    if in_frontmatter:
                        break  # end of frontmatter
                    in_frontmatter = True
                    continue
                if in_frontmatter:
                    m = re.match(r'^job_id:\s*"?(\d+)"?', line)
                    if m:
                        return m.group(1)
    except Exception:
        pass
    return ""


def recover():
    os.makedirs(DATA_DIR, exist_ok=True)

    if not os.path.isdir(VAULT_VACANCIES):
        print(f"❌ Vacancies directory not found: {VAULT_VACANCIES}")
        return

    md_files = [f for f in os.listdir(VAULT_VACANCIES) if f.endswith(".md")]
    print(f"📂 Found {len(md_files)} vacancy files in vault")

    job_ids = set()
    log_entries = {}

    for filename in sorted(md_files):
        filepath = os.path.join(VAULT_VACANCIES, filename)

        # Try filename first
        job_id = extract_job_id_from_filename(filename)

        # Fallback to frontmatter
        if not job_id:
            job_id = extract_job_id_from_frontmatter(filepath)

        if not job_id:
            print(f"  ⚠️ No job_id found: {filename}")
            continue

        job_ids.add(job_id)
        log_entries[job_id] = {
            "source": "recovered_from_vault",
            "filename": filename,
            "collected_at": datetime.datetime.now().strftime("%Y-%m-%d"),
        }

    # Build URL list
    urls = [
        f"https://www.linkedin.com/jobs/view/{jid}/"
        for jid in sorted(job_ids)
    ]

    # Save parsed file
    with open(PARSED_FILE, "w", encoding="utf-8") as f:
        json.dump(urls, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved {len(urls)} URLs → {PARSED_FILE}")

    # Save/merge log file
    existing_log = {}
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            existing_log = json.load(f)

    existing_log.update(log_entries)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(existing_log, f, indent=2, ensure_ascii=False)
    print(f"✅ Saved {len(log_entries)} entries → {LOG_FILE}")


if __name__ == "__main__":
    recover()
