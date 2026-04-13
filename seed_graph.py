"""Seed skills_graph.json from existing Skills/*.md files."""
import json
import os
import re

SKILLS_DIR = "obsidian_vault/Skills"
GRAPH_PATH = "data/skills_graph.json"

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


def main():
    graph = {"skills": {}}
    for fname in sorted(os.listdir(SKILLS_DIR)):
        if not fname.endswith(".md"):
            continue
        name = fname.replace(".md", "")
        path = os.path.join(SKILLS_DIR, fname)
        graph["skills"][name] = parse_skill_file(path)
        print(f"  ✅ {name}")

    with open(GRAPH_PATH, "w", encoding="utf-8") as f:
        json.dump(graph, f, indent=2, ensure_ascii=False)

    print(f"\n📊 Seeded {len(graph['skills'])} skills → {GRAPH_PATH}")


if __name__ == "__main__":
    main()
