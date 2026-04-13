"""
fix_company_backlinks.py — Retrospectively populate ## Jobs sections in Company files.

Scans all vacancy files, groups them by company, then updates each
Company .md file's ## Jobs section with [[wikilinks]] to their vacancies.

Usage:
    venv/bin/python fix_company_backlinks.py
"""
import os
import re

VAULT_BASE = os.path.abspath("obsidian_vault")
VACANCIES_DIR = os.path.join(VAULT_BASE, "Vacancies")
COMPANIES_DIR = os.path.join(VAULT_BASE, "Companies")

PLACEHOLDER = "_Backlinks from vacancy files will appear here._"


def extract_vacancy_info(filepath: str) -> dict | None:
    """Extract company name, job title, location, job_id from a vacancy file's frontmatter."""
    info = {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            in_frontmatter = False
            for line in f:
                stripped = line.strip()
                if stripped == "---":
                    if in_frontmatter:
                        break
                    in_frontmatter = True
                    continue
                if in_frontmatter:
                    if line.startswith("job_id:"):
                        info["job_id"] = line.split(":", 1)[1].strip().strip('"')
                    elif line.startswith("company:"):
                        raw = line.split(":", 1)[1].strip().strip('"')
                        # Extract name from [[Name]]
                        m = re.match(r"\[\[(.+?)]]", raw)
                        info["company"] = m.group(1) if m else raw
                    elif line.startswith("location:"):
                        info["location"] = line.split(":", 1)[1].strip()
            # Read the H1 title
            f.seek(0)
            for line in f:
                if line.startswith("# "):
                    info["job_title"] = line[2:].strip()
                    break
    except Exception:
        return None

    if "company" in info and "job_id" in info:
        info["filename_stem"] = os.path.splitext(os.path.basename(filepath))[0]
        return info
    return None


def build_jobs_section(vacancies: list[dict]) -> str:
    """Build the ## Jobs markdown section from a list of vacancy info dicts."""
    lines = []
    for v in sorted(vacancies, key=lambda x: x.get("job_title", "")):
        title = v.get("job_title", "Unknown Role")
        location = v.get("location", "")
        stem = v["filename_stem"]
        suffix = f" | {location}" if location else ""
        lines.append(f"- [[{stem}]] — {title}{suffix}")
    return "\n".join(lines) if lines else ""


def update_company_file(company_path: str, jobs_markdown: str) -> bool:
    """Update the ## Jobs section in a company .md file."""
    try:
        with open(company_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return False

    # Find ## Jobs section
    jobs_header_pattern = re.compile(r"(## Jobs\s*\n)")
    match = jobs_header_pattern.search(content)
    if not match:
        # Append ## Jobs at the end
        content = content.rstrip() + "\n\n## Jobs\n\n" + jobs_markdown + "\n"
    else:
        header_end = match.end()
        # Find next ## section (or end of file)
        next_section = re.search(r"\n## ", content[header_end:])
        if next_section:
            section_end = header_end + next_section.start()
        else:
            section_end = len(content)

        # Replace the Jobs section content
        content = (
            content[:header_end]
            + "\n" + jobs_markdown + "\n"
            + content[section_end:]
        )

    with open(company_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def main():
    if not os.path.isdir(VACANCIES_DIR):
        print(f"❌ Vacancies directory not found: {VACANCIES_DIR}")
        return

    # Step 1: Scan all vacancy files and group by company
    company_vacancies: dict[str, list[dict]] = {}
    md_files = [f for f in os.listdir(VACANCIES_DIR) if f.endswith(".md")]
    skipped = 0

    for filename in md_files:
        filepath = os.path.join(VACANCIES_DIR, filename)
        info = extract_vacancy_info(filepath)
        if info:
            company = info["company"]
            company_vacancies.setdefault(company, []).append(info)
        else:
            skipped += 1

    print(f"📂 Scanned {len(md_files)} vacancy files")
    print(f"🏢 Found {len(company_vacancies)} unique companies")
    if skipped:
        print(f"  ⚠️ Skipped {skipped} files (no company/job_id)")

    # Step 2: Update each company file
    updated = 0
    total_links = 0
    missing_companies = []

    for company_name, vacancies in sorted(company_vacancies.items()):
        company_file = os.path.join(COMPANIES_DIR, f"{company_name}.md")
        if not os.path.exists(company_file):
            missing_companies.append(company_name)
            continue

        jobs_md = build_jobs_section(vacancies)
        if update_company_file(company_file, jobs_md):
            updated += 1
            total_links += len(vacancies)

    print(f"\n✅ Updated {updated} company files with {total_links} vacancy links")

    if missing_companies:
        print(f"\n⚠️ {len(missing_companies)} companies have vacancies but no Company file:")
        for name in missing_companies[:10]:
            print(f"   - {name}")
        if len(missing_companies) > 10:
            print(f"   ... and {len(missing_companies) - 10} more")


if __name__ == "__main__":
    main()
