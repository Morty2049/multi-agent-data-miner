# LinkedIn Data Miner 🕷️

An autonomous pipeline to extract LinkedIn job vacancies and company metadata into structured Obsidian Markdown files.

The system mimics human browsing behavior and uses a persistent browser session to parse job pages into bi-directionally linked `.md` files for an Obsidian knowledge graph.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Playwright (Chromium)

```bash
# Setup environment
python3 -m venv venv
source venv/bin/activate
pip install playwright
playwright install chromium
```

### Usage

**Parse a single job URL:**
```bash
venv/bin/python parse_job.py https://www.linkedin.com/jobs/view/123456789/
```

**Batch process a queue file:**
```bash
venv/bin/python run_queue.py data/job_queue.json
venv/bin/python run_queue.py data/job_queue.json --limit 10
```

---

## 📂 Repository Structure

```
├── parse_job.py         # Core parser: single LinkedIn URL → Obsidian .md files
├── run_queue.py         # Batch runner: processes a JSON list of URLs
├── data/
│   ├── job_queue.json           # Queue of URLs to process
│   └── job_queue_prod_parsed.json  # Successfully processed URLs (auto-generated)
└── obsidian_vault/              # Output (ignored by Git)
    ├── Vacancies/               # One .md per job vacancy
    └── Companies/               # One .md per company
```

---

## 🧠 Data Flow

```
job_queue.json  →  run_queue.py  →  parse_job.py  →  Playwright (Chromium)
                                                            ↓
                              obsidian_vault/Vacancies/{Company}-{Title}.md
                              obsidian_vault/Companies/{Company}.md
```

1. **Extract**: Opens each URL in a persistent Chromium session.
2. **Transform**: Custom JavaScript + Regex converts the LinkedIn DOM into clean Markdown.
3. **Load**:
    - Vacancy file with full job description and YAML frontmatter.
    - Company file with overview, size, industry (visits the company's LinkedIn `/about/` page).
    - **Bi-directional link**: `company: "[[Company Name]]"` connects Vacancies ↔ Companies in Obsidian.

---

## ⚙️ Configuration

Settings are defined as constants at the top of `parse_job.py`:

| Constant | Default | Description |
| :--- | :--- | :--- |
| `SESSION_DIR` | `linkedin_session/` | Persistent Chromium user data (cookies, auth state) |
| `VAULT_BASE` | `obsidian_vault/` | Root path for all output Markdown files |


