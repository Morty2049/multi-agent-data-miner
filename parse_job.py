"""
parse_job.py — Parse a single LinkedIn job URL → Obsidian .md files (Vacancy + Company).

Usage:
    venv/bin/python parse_job.py https://www.linkedin.com/jobs/view/4342360269/

Outputs versioned files to obsidian_vault/Vacancies/ and obsidian_vault/Companies/
"""
import asyncio
import datetime
import json
import os
import re
import sys
from html.parser import HTMLParser

from playwright.async_api import async_playwright

SESSION_DIR = os.path.abspath("linkedin_session")
VAULT_BASE = os.path.abspath("obsidian_vault")


# ---------------------------------------------------------------------------
# DOM Extraction JS
# ---------------------------------------------------------------------------

EXTRACT_META_JS = r"""
() => {
    const r = {};
    r.page_title = document.title;
    
    const compLink = document.querySelector('a[href*="/company/"]');
    r.company_name = compLink ? compLink.innerText.trim() : '';
    r.company_href = compLink ? compLink.href.split('?')[0] : '';
    
    // Top card: find the block with applicant/apply info
    const keywords = ['applicant', 'clicked apply', 'people'];
    const allEls = document.querySelectorAll('div, span, p');
    for (const el of allEls) {
        const t = el.innerText.trim();
        if (t.length > 20 && t.length < 500 && keywords.some(k => t.includes(k))) {
            r.top_card = t;
            break;
        }
    }
    
    // Fallback: search body text for line with middle-dot separator
    if (!r.top_card) {
        const bodyText = document.body.innerText;
        const dot = String.fromCharCode(183);
        const lines = bodyText.split('\n');
        for (const line of lines) {
            if (line.includes(dot) && (line.includes('applicant') || line.includes('ago') || line.includes('clicked'))) {
                r.top_card = line.trim();
                break;
            }
        }
    }
    
    return r;
}
"""

EXTRACT_DESC_JS = r"""
() => {
    const descSels = ['#job-details', '.jobs-description__content', '.jobs-box__html-content', 'article'];
    for (const sel of descSels) {
        const el = document.querySelector(sel);
        if (el && el.innerText.trim().length > 50) {
            return {html: el.innerHTML, text: el.innerText.trim(), selector: sel, method: 'selector'};
        }
    }
    const body = document.body.innerText;
    return {html: '', text: body, selector: 'body', method: 'fulltext'};
}
"""

EXTRACT_COMPANY_JS = r"""
() => {
    const r = {};
    
    // Overview: look for <p> inside <main> or <section>, skipping nav
    const aboutSection = document.querySelector('section.org-about-module, [class*="about"]');
    if (aboutSection) {
        const p = aboutSection.querySelector('p');
        if (p && p.innerText.trim().length > 50) {
            r.overview = p.innerText.trim();
        }
    }
    if (!r.overview) {
        const allP = document.querySelectorAll('main p, section p, article p');
        for (const el of allP) {
            const t = el.innerText.trim();
            if (t.length > 100 && t.length < 3000) {
                r.overview = t;
                break;
            }
        }
    }
    
    // Parse label-value pairs from body text
    const allText = document.body.innerText;
    const keys = ['Industry', 'Company size', 'Headquarters', 'Website'];
    const keysRu = ['\u041e\u0442\u0440\u0430\u0441\u043b\u044c', '\u0420\u0430\u0437\u043c\u0435\u0440 \u043a\u043e\u043c\u043f\u0430\u043d\u0438\u0438', '\u0428\u0442\u0430\u0431-\u043a\u0432\u0430\u0440\u0442\u0438\u0440\u0430', '\u0412\u0435\u0431-\u0441\u0430\u0439\u0442'];
    const fieldNames = ['industry', 'company_size', 'headquarters', 'website'];
    
    for (let i = 0; i < keys.length; i++) {
        for (const key of [keys[i], keysRu[i]]) {
            const pattern = new RegExp(key + '\\n([^\\n]+)');
            const match = allText.match(pattern);
            if (match) { r[fieldNames[i]] = match[1].trim(); break; }
        }
    }
    
    // Jobs links
    const jobLinks = document.querySelectorAll('a[href*="/jobs/search"]');
    const jobUrls = [];
    for (const a of jobLinks) {
        if (a.href && !jobUrls.includes(a.href)) jobUrls.push(a.href);
    }
    r.job_links = jobUrls.slice(0, 3);
    
    return r;
}
"""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_title_from_page_title(page_title: str) -> str:
    """Extract job title from 'Job Title | Company | LinkedIn'."""
    parts = [p.strip() for p in page_title.split(" | ")]
    parts[0] = re.sub(r'^\(\d+\)\s*', '', parts[0])
    if len(parts) >= 3 and parts[-1] == "LinkedIn":
        return " | ".join(parts[:-2])
    return parts[0] if parts else "Unknown Role"


def parse_top_card(top_card: str) -> dict:
    """Parse the metadata block: location \u00b7 reposted \u00b7 applicants + employment."""
    result = {"location": "", "reposted": "", "applies": "", "employment": "Full-time"}
    if not top_card:
        return result
    
    for line in top_card.split("\n"):
        if "\u00b7" in line:
            parts = [p.strip() for p in line.split("\u00b7")]
            if len(parts) >= 1:
                result["location"] = parts[0]
            for p in parts[1:]:
                p_lower = p.lower()
                if "reposted" in p_lower or "ago" in p_lower:
                    result["reposted"] = p.replace("Reposted ", "").strip()
                elif "applicant" in p_lower or "clicked apply" in p_lower or "people" in p_lower:
                    result["applies"] = p.strip()
            break
    
    emp_types = ["Full-time", "Part-time", "Contract", "Internship", "Temporary", "Volunteer"]
    for emp in emp_types:
        if emp in top_card:
            result["employment"] = emp
            break
    
    return result


def job_id_from_url(url: str) -> str:
    m = re.search(r"/jobs/view/(\d+)", url)
    return m.group(1) if m else ""


def html_to_markdown(html: str) -> str:
    """Convert LinkedIn job description HTML to clean Markdown."""
    if not html:
        return ""
    text = html.replace("\r\n", "\n").replace("\r", "\n")
    
    # Convert tags to markdown
    text = re.sub(r'<strong>(.*?)</strong>', r'**\1**', text, flags=re.DOTALL)
    text = re.sub(r'<b>(.*?)</b>', r'**\1**', text, flags=re.DOTALL)
    text = re.sub(r'<em>(.*?)</em>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<i>(.*?)</i>', r'*\1*', text, flags=re.DOTALL)
    text = re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'\n## \1\n', text, flags=re.DOTALL)
    
    # Lists
    text = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1', text, flags=re.DOTALL)
    text = re.sub(r'</?[ou]l[^>]*>', '', text)
    
    # Paragraphs and breaks
    text = re.sub(r'<br\s*/?>', '\n', text)
    text = re.sub(r'</p>', '\n', text)
    text = re.sub(r'<p[^>]*>', '', text)
    
    # Remove remaining HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    
    # HTML entities
    text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&nbsp;', ' ').replace('&quot;', '"')
    
    # Clean whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +\n', '\n', text)
    text = re.sub(r'\n +', '\n', text)
    
    return text.strip()


def safe_filename(text: str) -> str:
    return re.sub(r"[^\w\s\-]", "", text, flags=re.UNICODE).strip()


def sanitize_text(text: str) -> str:
    """Remove lone Unicode surrogates that break utf-8 encoding."""
    if not text:
        return text
    # Encode to utf-8, replacing surrogates with '?', then decode back
    return text.encode("utf-8", errors="replace").decode("utf-8")


def _extract_description_from_fulltext(fulltext: str) -> str:
    """Extract the job description section from LinkedIn's full body text."""
    start_markers = ["About the job\n", "About the job\r\n"]
    start_idx = 0
    for marker in start_markers:
        idx = fulltext.find(marker)
        if idx >= 0:
            start_idx = idx + len(marker)
            break
    
    if start_idx == 0:
        for alt in ["Company Description\n", "Job Description\n"]:
            idx = fulltext.find(alt)
            if idx >= 0:
                start_idx = idx
                break
    
    end_markers = [
        "\nShow less",
        "\n\u2026 more",
        "\nSet alert",
        "\nAbout the company",
        "\nSimilar jobs",
        "\nPeople also viewed",
        "\nActivity on this job",
    ]
    end_idx = len(fulltext)
    for marker in end_markers:
        idx = fulltext.find(marker, start_idx)
        if idx >= 0 and idx < end_idx:
            end_idx = idx
    
    desc = fulltext[start_idx:end_idx].strip()
    return desc if len(desc) > 30 else "_No description extracted_"


# ---------------------------------------------------------------------------
# Markdown builders
# ---------------------------------------------------------------------------

def build_vacancy_md(data: dict) -> str:
    return f"""---
date: {data['date']}
type: vacancy
source: linkedin_recommended
job_id: "{data['job_id']}"
company: "[[{data['company']}]]"
location: {data['location']}
reposted: {data['reposted']}
applies: {data['applies']}
employment: {data['employment']}
job_url: {data['job_url']}
apply_url: {data['apply_url']}
company_url: {data['company_url']}
tags:
  - vacancy
  - linkedin_recommended
---
# {data['job_title']}

**Company:** [[{data['company']}]]
**Location:** {data['location']}
**Reposted:** {data['reposted']}
**Applies:** {data['applies']}
**Employment:** {data['employment']}

## Job Description

## About the job

{data['description']}
"""


def build_company_md(data: dict) -> str:
    return f"""---
type: "[[Company]]"
name: {data.get('company', 'Unknown')}
industry: {data.get('industry', 'Unknown')}
headquarters: {data.get('headquarters', 'Unknown')}
link: {data.get('company_url', '')}
website: {data.get('website', 'Unknown')}
Company size: {data.get('company_size', 'Unknown')}
---
## Overview

{data.get('overview', '_No overview extracted._')}


## Jobs

{data.get('jobs_section', '')}
"""


# ---------------------------------------------------------------------------
# Company page parser
# ---------------------------------------------------------------------------

async def parse_company_page(company_url: str, company_name: str, page=None) -> dict:
    """Navigate to a LinkedIn company page and extract metadata."""
    data = {"company": company_name, "company_url": company_url}
    
    try:
        about_url = company_url.rstrip("/").replace("/life", "") + "/about/"
        await page.goto(about_url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(4)
        
        raw = await page.evaluate(EXTRACT_COMPANY_JS)
        
        data["industry"] = raw.get("industry", "Unknown")
        data["headquarters"] = raw.get("headquarters", "Unknown")
        data["website"] = raw.get("website", "Unknown")
        data["company_size"] = raw.get("company_size", "Unknown")
        data["overview"] = raw.get("overview", "_No overview extracted._")
        
        job_links = raw.get("job_links", [])
        if job_links:
            jobs_lines = ["### Recommended jobs for you", "Based on your Profile information", ""]
            for link in job_links:
                jobs_lines.append(link)
            data["jobs_section"] = "\n".join(jobs_lines)
    except Exception as e:
        print(f"  \u26a0\ufe0f Company parsing failed: {e}")
    
    return data


def append_job_to_company(comp_path: str, vac_filename_stem: str, job_title: str, location: str, job_id: str):
    """Append a [[wikilink]] for a vacancy into the company file's ## Jobs section.
    
    Idempotent: skips if job_id already linked.
    """
    if not os.path.exists(comp_path):
        return
    
    try:
        with open(comp_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return
    
    # Skip if this job_id is already linked
    if f"({job_id})" in content:
        return
    
    suffix = f" | {sanitize_text(location)}" if location else ""
    link_line = f"- [[{vac_filename_stem}]] — {sanitize_text(job_title)}{suffix}"
    
    # Find ## Jobs section
    jobs_idx = content.find("## Jobs")
    if jobs_idx < 0:
        # Append section at end
        content = content.rstrip() + "\n\n## Jobs\n\n" + link_line + "\n"
    else:
        # Find where to insert (after ## Jobs\n\n)
        insert_pos = content.find("\n", jobs_idx)
        if insert_pos < 0:
            insert_pos = len(content)
        else:
            insert_pos += 1  # past the newline after header
        
        # Find next ## section
        next_section = content.find("\n## ", insert_pos)
        if next_section < 0:
            # Append at end
            content = content.rstrip() + "\n" + link_line + "\n"
        else:
            # Insert before next section
            content = (
                content[:next_section].rstrip()
                + "\n" + link_line
                + "\n" + content[next_section:]
            )
    
    with open(comp_path, "w", encoding="utf-8") as f:
        f.write(content)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def parse_job(url: str, version: str = "", page=None):
    """Parse a single LinkedIn job URL into Obsidian .md files.
    
    If *page* is provided (batch mode), reuses it. Otherwise opens own browser.
    """
    job_id = job_id_from_url(url)
    if not job_id:
        print(f"ERROR: Cannot extract job ID from URL: {url}")
        return
    
    print(f"Parsing job {job_id}...")
    
    own_context = page is None
    ctx = None
    
    try:
        if own_context:
            pw_inst = await async_playwright().start()
            ctx = await pw_inst.chromium.launch_persistent_context(
                user_data_dir=SESSION_DIR, headless=True,
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
            )
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await asyncio.sleep(4)
        
        # Step 1: Extract metadata
        raw = await page.evaluate(EXTRACT_META_JS)
        
        # Step 2: Scroll to trigger lazy-loaded description
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 3)")
        await asyncio.sleep(2)
        
        # Step 3: Click "Show more" if present
        for sel in [
            "button.jobs-description__footer-button",
            "button[aria-label='Show more']",
            "button[aria-label*='more']",
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(1)
                    break
            except Exception:
                continue
        
        # Step 4: Extract description
        desc_data = await page.evaluate(EXTRACT_DESC_JS)
        desc_method = desc_data.get("method", "")
        desc_html = desc_data.get("html", "")
        desc_text = desc_data.get("text", "")
        
        if desc_method == "selector" and desc_html:
            description = html_to_markdown(desc_html)
        elif desc_method == "fulltext" and desc_text:
            description = _extract_description_from_fulltext(desc_text)
        else:
            description = "_No description extracted_"
        
        # Parse fields
        job_title = parse_title_from_page_title(raw.get("page_title", ""))
        company = raw.get("company_name", "Unknown Company")
        company_url = raw.get("company_href", "")
        top = parse_top_card(raw.get("top_card", ""))
        
        data = {
            "date": datetime.datetime.now().strftime("%Y-%m-%d"),
            "job_id": job_id,
            "job_title": job_title,
            "company": company,
            "location": top["location"],
            "reposted": top["reposted"],
            "applies": top["applies"],
            "employment": top["employment"],
            "job_url": url,
            "apply_url": "Easy Apply (LinkedIn)",
            "company_url": company_url,
            "description": description,
        }
        
        # Write vacancy
        vac_dir = os.path.join(VAULT_BASE, "Vacancies")
        os.makedirs(vac_dir, exist_ok=True)
        safe_company = safe_filename(company)[:40]
        safe_title = safe_filename(job_title)[:60]
        vac_suffix = f"_({version})" if version else ""
        vac_filename = f"{safe_company}_-_{safe_title}_({job_id}){vac_suffix}.md".replace(" ", "_")
        vac_path = os.path.join(vac_dir, vac_filename)
        
        with open(vac_path, "w", encoding="utf-8") as f:
            f.write(build_vacancy_md(data))
        print(f"\u2705 Vacancy: {vac_path}")
        
        # Derive the vacancy filename stem for wikilinks
        vac_filename_stem = os.path.splitext(os.path.basename(vac_path))[0]
        
        # Step 5: Parse company page (reuse the same browser page)
        comp_dir = os.path.join(VAULT_BASE, "Companies")
        os.makedirs(comp_dir, exist_ok=True)
        comp_suffix = f"_({version})" if version else ""
        comp_filename = f"{safe_company}{comp_suffix}.md"
        comp_path = os.path.join(comp_dir, comp_filename)
        
        # Skip if company file already exists and is populated
        if os.path.exists(comp_path) and os.path.getsize(comp_path) > 150:
            print(f"  Company file already exists, skipping: {comp_filename}")
        else:
            comp_data = {"company": company, "company_url": company_url}
            if company_url:
                print(f"  Parsing company page: {company_url}")
                comp_data = await parse_company_page(company_url, company, page=page)
            
            with open(comp_path, "w", encoding="utf-8") as f:
                f.write(build_company_md(comp_data))
            print(f"\u2705 Company: {comp_path}")
        
        # Append vacancy link to company file's ## Jobs section
        append_job_to_company(comp_path, vac_filename_stem, job_title, top["location"], job_id)
        print(f"  -> Linked to company: {safe_company}")
        # Print summary
        print(f"  \u2192 {job_title} @ {company} | {top['location']} | desc: {len(description)} chars ({desc_method})")
        
    finally:
        if own_context and ctx:
            await ctx.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: venv/bin/python parse_job.py <linkedin_job_url> [--dev]")
        sys.exit(1)
    version = "v.1" if "--dev" in sys.argv else ""
    url = [a for a in sys.argv[1:] if not a.startswith("--")][0]
    asyncio.run(parse_job(url, version=version))

