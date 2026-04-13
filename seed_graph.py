"""Seed skills_graph.json from existing Skills/*.md files."""
import json
import os
import re

SKILLS_DIR = "obsidian_vault/Skills"
GRAPH_PATH = "data/skills_graph.json"

# Regex that matches vacancy filenames: contain a job ID (long digit sequence)
_VACANCY_ID_RE = re.compile(r"\d{8,}")


def parse_skill_file(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    info = {"about": "", "parent": [], "children": [], "mentions": []}

    # Extract About
    m = re.search(r"## About\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    if m:
        info["about"] = m.group(1).strip()

    # Extract Parent links
    m = re.search(r"## Parent\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    if m:
        info["parent"] = re.findall(r"\[\[(.+?)\]\]", m.group(1))

    # Extract Children links
    m = re.search(r"## Children\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    if m:
        info["children"] = re.findall(r"\[\[(.+?)\]\]", m.group(1))

    # Extract Mentions links
    m = re.search(r"## Mentions\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    if m:
        info["mentions"] = re.findall(r"\[\[(.+?)\]\]", m.group(1))

    return info


def _validate(info: dict, existing_names: set[str]) -> list[str]:
    """Return list of warning strings for a skill's data integrity."""
    warnings = []
    for parent in info["parent"]:
        # Detect vacancy IDs accidentally placed in Parent section
        if _VACANCY_ID_RE.search(parent):
            warnings.append(f"CORRUPTION: Parent contains vacancy ID: [[{parent}]]")
        elif parent not in existing_names:
            warnings.append(f"BROKEN_PARENT: [[{parent}]] not in Skills/")
    for child in info["children"]:
        if child not in existing_names:
            warnings.append(f"BROKEN_CHILD: [[{child}]] not in Skills/")
    return warnings


def main():
    skill_files = {
        fname.replace(".md", ""): os.path.join(SKILLS_DIR, fname)
        for fname in sorted(os.listdir(SKILLS_DIR))
        if fname.endswith(".md")
    }
    existing_names = set(skill_files.keys())

    graph = {"skills": {}}
    corruption_count = 0
    broken_ref_count = 0

    for name, path in skill_files.items():
        info = parse_skill_file(path)
        warnings = _validate(info, existing_names)

        for w in warnings:
            if w.startswith("CORRUPTION"):
                print(f"  ⚠️  {name}: {w}")
                corruption_count += 1
                # Strip corrupted parent entries so they don't pollute graph
                info["parent"] = [
                    p for p in info["parent"] if not _VACANCY_ID_RE.search(p)
                ]
            elif w.startswith("BROKEN"):
                broken_ref_count += 1  # log silently; these get fixed by merge_skills

        graph["skills"][name] = info

    tmp_path = GRAPH_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, GRAPH_PATH)

    print(f"\n📊 Seeded {len(graph['skills'])} skills → {GRAPH_PATH}")
    if corruption_count:
        print(f"   ⚠️  {corruption_count} corruption issues (vacancy IDs in Parent) — stripped")
    if broken_ref_count:
        print(f"   ℹ️  {broken_ref_count} broken parent/child refs — run merge_skills.py to fix")


if __name__ == "__main__":
    main()
