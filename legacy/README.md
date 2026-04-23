# legacy/

Offline, one-shot scripts that operated on the Obsidian vault before the
Chrome plugin became the primary write path. Kept for maintenance of the
historical `Skills/` graph and for occasional repair passes. **Not part
of the live product** — the Chrome plugin + API server work without any
of these running.

All scripts expect to be run from the repo root (paths like
`obsidian_vault/` and `data/` are resolved relative to the current
working directory, not `__file__`):

```bash
venv/bin/python legacy/<script>.py [args]
```

## Inventory

| Script | Purpose | External deps |
|---|---|---|
| `skills_miner_adk.py` | Two-agent Google-ADK pipeline: Extractor pulls skill candidates from a vacancy, Reviewer normalizes them against the existing graph + synonyms, writes `Skills/*.md` and `[[wikilinks]]` back into the vacancy. | `google-adk`, `GOOGLE_API_KEY` |
| `skills_tools.py` | Pure-Python file-I/O helpers used as ADK FunctionTools by `skills_miner_adk.py`. Not runnable on its own. | — |
| `reorganize_vault.py` | One-off LLM dedup + cluster-tag pass across `Skills/`. Produces a manifest in `data/reorganize_manifest.json`, then `--apply` merges skill files and rewrites wikilinks. | `google-genai`, `GOOGLE_API_KEY` |
| `merge_skills.py` | Rule-based (no LLM) dedup + broken-link repair. Safer than `reorganize_vault.py`; use first. | — |
| `seed_graph.py` | Rebuild `data/skills_graph.json` from the current `Skills/*.md`. Run after manual edits. | — |
| `build_manifest.py` | Build a static rename/delete manifest for bulk vault operations. | — |
| `fix_company_backlinks.py` | Repair `Companies/*.md` backlink sections so each company file lists every vacancy that references it. Safe to run any time. | — |
| `recover_parsed.py` | Reconstruct `data/skills_mined.json` from existing `Vacancies/*.md` frontmatter (if the tracker got lost). | — |

## When to use which

- **"Company files are out of sync with vacancies"** → `fix_company_backlinks.py`
- **"I edited `Skills/*.md` by hand; graph JSON is stale"** → `seed_graph.py`
- **"I have a bunch of near-duplicate skill notes"** → `merge_skills.py` first, then `reorganize_vault.py --analyze` to see if the LLM pass catches more
- **"I scraped new vacancies and want them linked into the skills graph"** → `skills_miner_adk.py --limit 10 --dry-run` first, then for real

## LLM setup

Scripts that call Gemini (`skills_miner_adk.py`, `reorganize_vault.py`)
read `GOOGLE_API_KEY` from `.env` via `python-dotenv`. Get a key at
<https://aistudio.google.com/apikey>.

## Why "legacy"?

These scripts came from the pre-plugin era when vacancies were scraped
via a Playwright CLI and the whole skills graph was maintained in batch
mode. The Chrome plugin replaces the scraping side. The skills
enrichment step is still useful but is no longer the central loop, and
the scripts here aren't being actively rewritten — only used as-is for
one-off vault repairs.
