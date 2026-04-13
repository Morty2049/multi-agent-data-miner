"""
skills_tools.py — Pure Python tools for the Skills Miner ADK agent.

Provides file I/O functions registered as ADK FunctionTools:
- Reading vacancy files
- Inserting [[wikilinks]]
- Creating/updating skill notes
- Managing graph state and synonyms
"""
import fcntl
import json
import os
import re

VAULT_BASE = os.path.abspath("obsidian_vault")
SKILLS_DIR = os.path.join(VAULT_BASE, "Skills")
VACANCIES_DIR = os.path.join(VAULT_BASE, "Vacancies")
DATA_DIR = os.path.abspath("data")

GRAPH_PATH = os.path.join(DATA_DIR, "skills_graph.json")
SYNONYMS_PATH = os.path.join(DATA_DIR, "skill_synonyms.json")
MINED_PATH = os.path.join(DATA_DIR, "skills_mined.json")
GRAPH_LOCK_PATH = os.path.join(DATA_DIR, "skills_graph.lock")

os.makedirs(SKILLS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_json(path: str, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def _save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_synonyms() -> dict:
    return _load_json(SYNONYMS_PATH, {})


def save_synonyms(synonyms: dict):
    _save_json(SYNONYMS_PATH, synonyms)


def load_graph() -> dict:
    return _load_json(GRAPH_PATH, {"skills": {}})


def save_graph(graph: dict):
    """Atomic write: write to temp file then rename to avoid partial reads."""
    tmp_path = GRAPH_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, GRAPH_PATH)


def load_mined() -> list:
    return _load_json(MINED_PATH, [])


def save_mined(mined: list):
    _save_json(MINED_PATH, mined)


# ---------------------------------------------------------------------------
# ADK-compatible tool functions
# ---------------------------------------------------------------------------

def list_unprocessed_vacancies() -> list[str]:
    """Returns filenames of vacancies not yet processed by the skills miner."""
    mined = set(load_mined())
    all_files = sorted([
        f for f in os.listdir(VACANCIES_DIR) if f.endswith(".md")
    ])
    return [f for f in all_files if f not in mined]


def read_vacancy(filename: str) -> str:
    """Reads and returns the full content of a vacancy markdown file."""
    path = os.path.join(VACANCIES_DIR, filename)
    if not os.path.exists(path):
        return f"ERROR: File not found: {filename}"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_graph_state() -> str:
    """Returns a compact skills graph for the reviewer agent.

    Sends only skill names — avoids megabyte-sized payloads for large graphs.
    The reviewer uses this to check canonical names and avoid duplicates.
    """
    graph = load_graph()
    names = sorted(graph.get("skills", {}).keys())
    return json.dumps(names, ensure_ascii=False)


def get_graph_slice(skill_names: list[str]) -> str:
    """Returns a subgraph slice for specific skills + their parents.

    Used by the reviewer when it needs hierarchy context, not just name lookup.
    """
    graph = load_graph()
    skills = graph.get("skills", {})
    relevant = set(skill_names)
    for name in list(relevant):
        if name in skills:
            relevant.update(skills[name].get("parent", []))
    summary = {
        name: {"parent": skills[name].get("parent", []), "children": skills[name].get("children", [])}
        for name in sorted(relevant)
        if name in skills
    }
    return json.dumps(summary, ensure_ascii=False, indent=2)


def get_synonyms() -> str:
    """Returns the synonym dictionary as a JSON string."""
    return json.dumps(load_synonyms(), ensure_ascii=False, indent=2)


def insert_wikilinks(filename: str, replacements: list[dict]) -> str:
    """Inserts [[wikilinks]] into a vacancy file.

    Each replacement dict should have:
        - original: the text to find in the vacancy (e.g., "K8s")
        - canonical: the canonical skill name (e.g., "Kubernetes")

    If original == canonical, inserts [[original]].
    If original != canonical, inserts [[canonical|original]] (Obsidian alias).
    
    Returns a summary of changes made.
    """
    path = os.path.join(VACANCIES_DIR, filename)
    if not os.path.exists(path):
        return f"ERROR: File not found: {filename}"

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Split into frontmatter and body to protect YAML headers
    parts = content.split("---", 2)
    if len(parts) >= 3:
        frontmatter = parts[0] + "---" + parts[1] + "---"
        body = parts[2]
    else:
        frontmatter = ""
        body = content

    changes = []
    for rep in replacements:
        original = rep.get("original", "")
        canonical = rep.get("canonical", original)
        if not original:
            continue

        # Don't re-link if already linked
        # Check if the original is already inside [[...]]
        already_linked = re.search(
            r'\[\[' + re.escape(canonical) + r'(\|[^\]]+)?\]\]', body
        )
        if already_linked:
            continue

        # Build the wikilink
        if original == canonical:
            wikilink = f"[[{canonical}]]"
        else:
            wikilink = f"[[{canonical}|{original}]]"

        # Replace all standalone occurrences (not inside existing [[ ]])
        pattern = r'(?<!\[\[)(?<!\|)\b' + re.escape(original) + r'\b(?!\]\])(?!\|)'
        new_body, count = re.subn(pattern, wikilink, body)
        if count > 0:
            body = new_body
            changes.append(f"  '{original}' → {wikilink} (×{count})")

    if changes:
        with open(path, "w", encoding="utf-8") as f:
            f.write(frontmatter + body)
        return f"OK: {len(changes)} links inserted in {filename}:\n" + "\n".join(changes)
    else:
        return f"OK: No new links needed in {filename}"


def upsert_skill(
    name: str,
    about: str,
    tags: list[str],
    parent: list[str],
    children: list[str],
    vacancy_filename: str,
) -> str:
    """Creates or updates a skill note in the Skills/ directory.

    Idempotent: if the skill file already exists, only adds the new vacancy
    to Mentions (if not already there) and merges parent/children.

    Returns a summary of the action taken.
    """
    safe_name = re.sub(r"[/\\:*?\"<>|]", "_", name)
    skill_path = os.path.join(SKILLS_DIR, f"{safe_name}.md")

    # Derive the vacancy stem (without .md) for wikilinks
    vac_stem = vacancy_filename.replace(".md", "") if vacancy_filename.endswith(".md") else vacancy_filename
    mention_link = f"[[{vac_stem}]]"

    # Update graph state with exclusive file lock to prevent concurrent corruption
    lock_file = open(GRAPH_LOCK_PATH, "w")
    fcntl.flock(lock_file, fcntl.LOCK_EX)
    graph = load_graph()
    skills = graph.setdefault("skills", {})

    if os.path.exists(skill_path):
        # --- UPDATE existing skill ---
        with open(skill_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Add mention if not already present
        action = "updated"
        if mention_link not in content:
            # Find ## Mentions section and append
            if "## Mentions" in content:
                content = content.rstrip() + f"\n- {mention_link}\n"
            else:
                content = content.rstrip() + f"\n\n## Mentions\n- {mention_link}\n"
            action = "updated (added mention)"

        # Merge parent links — create ## Parent section if missing
        for p in parent:
            p_link = f"[[{p}]]"
            if p_link not in content:
                if "## Parent" in content:
                    content = content.replace("## Parent\n", f"## Parent\n- {p_link}\n", 1)
                else:
                    # No Parent section — insert before ## Mentions (or at end)
                    if "## Mentions" in content:
                        content = content.replace("## Mentions", f"## Parent\n- {p_link}\n\n## Mentions", 1)
                    else:
                        content = content.rstrip() + f"\n\n## Parent\n- {p_link}\n"

        # Merge children links — create ## Children section if missing
        for c in children:
            c_link = f"[[{c}]]"
            if c_link not in content:
                if "## Children" in content:
                    content = content.replace("## Children\n", f"## Children\n- {c_link}\n", 1)
                elif "## Mentions" in content:
                    content = content.replace("## Mentions", f"## Children\n- {c_link}\n\n## Mentions", 1)
                else:
                    content = content.rstrip() + f"\n\n## Children\n- {c_link}\n"

        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Update graph
        if name in skills:
            existing_parents = set(skills[name].get("parent", []))
            existing_children = set(skills[name].get("children", []))
            existing_mentions = set(skills[name].get("mentions", []))
            skills[name]["parent"] = sorted(existing_parents | set(parent))
            skills[name]["children"] = sorted(existing_children | set(children))
            skills[name]["mentions"] = sorted(existing_mentions | {vac_stem})

    else:
        # --- CREATE new skill ---
        action = "created"
        tags_str = ", ".join(tags) if tags else "skill"
        parent_lines = "\n".join(f"- [[{p}]]" for p in parent) if parent else "- (none)"
        children_section = ""
        if children:
            children_lines = "\n".join(f"- [[{c}]]" for c in children)
            children_section = f"\n## Children\n{children_lines}\n"

        content = f"""---
type: skill
tags: [{tags_str}]
---
# {name}

## About
{about}

## Parent
{parent_lines}
{children_section}
## Mentions
- {mention_link}
"""
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(content)

        skills[name] = {
            "about": about,
            "parent": parent,
            "children": children,
            "mentions": [vac_stem],
        }

    save_graph(graph)
    fcntl.flock(lock_file, fcntl.LOCK_UN)
    lock_file.close()
    return f"OK: Skill '{name}' {action}"


def mark_processed(filename: str) -> str:
    """Marks a vacancy file as processed so it won't be re-processed."""
    mined = load_mined()
    mined_set = set(mined)
    if filename not in mined_set:
        mined.append(filename)
        save_mined(mined)
    return f"OK: {filename} marked as processed"


def add_synonym(abbreviation: str, canonical: str) -> str:
    """Adds a new synonym mapping to the dictionary."""
    synonyms = load_synonyms()
    synonyms[abbreviation] = canonical
    save_synonyms(synonyms)
    return f"OK: Added synonym '{abbreviation}' → '{canonical}'"
