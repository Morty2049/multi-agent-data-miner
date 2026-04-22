"""
merge_skills.py — Skills graph cleanup and link repair tool.

Fixes two categories of problems:
  1. Duplicate skill files (same skill, different filename casing/punctuation)
  2. Broken [[wikilinks]] in vacancies pointing to non-existent Skills/ files

Usage:
    venv/bin/python merge_skills.py              # dry-run: report only
    venv/bin/python merge_skills.py --apply      # apply all fixes
    venv/bin/python merge_skills.py --apply --backup-only  # backup then stop
    venv/bin/python merge_skills.py --restore    # rollback from latest backup
"""

import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime

SKILLS_DIR = "obsidian_vault/Skills"
VACANCIES_DIR = "obsidian_vault/Vacancies"
DATA_DIR = "data"
GRAPH_PATH = os.path.join(DATA_DIR, "skills_graph.json")
SYNONYMS_PATH = os.path.join(DATA_DIR, "skill_synonyms.json")
BACKUP_DIR = os.path.join(DATA_DIR, "skills_backup")


def load_synonyms() -> dict[str, str]:
    """Load synonym dictionary: abbreviation → canonical skill name."""
    if os.path.exists(SYNONYMS_PATH):
        with open(SYNONYMS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(name: str) -> str:
    """Normalize skill name for duplicate detection: lowercase, strip separators.

    Only strips whitespace, hyphens, underscores, and slashes — NOT dots or
    special chars. This correctly separates C++ from C#, .NET from NET,
    and Node.js from Vue.js while still merging "CI_CD" with "CI/CD".
    """
    name = os.path.splitext(name)[0]           # remove .md if present
    name = name.lower()
    name = re.sub(r"[\s\-_/\\]", "", name)     # strip separators only
    return name


# ---------------------------------------------------------------------------
# Phase 1: Analysis
# ---------------------------------------------------------------------------

def build_skills_index() -> dict[str, list[str]]:
    """Returns normalized_key → [list of filenames] mapping."""
    index: dict[str, list[str]] = defaultdict(list)
    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith(".md"):
            continue
        key = normalize(fname)
        index[key].append(fname)
    return dict(index)


def find_duplicate_groups(index: dict[str, list[str]]) -> list[list[str]]:
    """Returns groups of files sharing the same normalized key (duplicates)."""
    return [files for files in index.values() if len(files) > 1]


def extract_wikilinks(content: str) -> list[str]:
    """Extract all [[Target]] and [[Target|Display]] targets from text."""
    targets = []
    for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content):
        targets.append(m.group(1).strip())
    return targets


def find_broken_links(index: dict[str, list[str]]) -> dict[str, list[dict]]:
    """
    Scans all vacancies for [[links]] where Skills/<target>.md does not exist.
    Uses normalization + synonym dictionary for resolution.
    Returns { vacancy_filename: [ {original, suggestion} ] }
    """
    # Build fast lookup: normalized key → canonical filename (without .md)
    norm_to_canonical: dict[str, str] = {}
    for key, files in index.items():
        # Pick the longest filename as canonical (usually most complete)
        canonical = sorted(files, key=len, reverse=True)[0]
        norm_to_canonical[key] = os.path.splitext(canonical)[0]

    # Load synonym dictionary for fallback resolution
    synonyms = load_synonyms()
    # Build reverse lookup: synonym value (canonical) → existing skill filename
    synonym_targets: dict[str, str] = {}
    for abbrev, canonical in synonyms.items():
        # Check if the canonical name has an existing file
        if f"{canonical}.md" in set(os.listdir(SKILLS_DIR)):
            synonym_targets[abbrev] = canonical

    # Collect exact set of existing skill names (without .md)
    existing_names: set[str] = {
        os.path.splitext(f)[0]
        for f in os.listdir(SKILLS_DIR)
        if f.endswith(".md")
    }

    broken: dict[str, list[dict]] = {}

    for fname in sorted(os.listdir(VACANCIES_DIR)):
        if not fname.endswith(".md"):
            continue
        path = os.path.join(VACANCIES_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        file_broken = []
        seen = set()
        for target in extract_wikilinks(content):
            if target in existing_names or target in seen:
                continue
            seen.add(target)
            suggestion = None

            # Strategy 1: Normalize and match
            norm_target = normalize(target)
            suggestion = norm_to_canonical.get(norm_target)

            # Strategy 2: Direct synonym lookup
            if suggestion is None and target in synonym_targets:
                suggestion = synonym_targets[target]

            # Strategy 3: Normalized synonym lookup
            if suggestion is None:
                for abbrev, canonical in synonym_targets.items():
                    if normalize(abbrev) == norm_target:
                        suggestion = canonical
                        break

            if suggestion and suggestion != target:
                file_broken.append({"original": target, "suggestion": suggestion})
            elif suggestion is None:
                file_broken.append({"original": target, "suggestion": None})

        if file_broken:
            broken[fname] = file_broken

    return broken


def find_self_references() -> list[tuple[str, str]]:
    """Find skill files that reference themselves in their Parent section."""
    issues = []
    for fname in os.listdir(SKILLS_DIR):
        if not fname.endswith(".md"):
            continue
        skill_name = os.path.splitext(fname)[0]
        path = os.path.join(SKILLS_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        # Find ## Parent section
        m = re.search(r"## Parent\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
        if m:
            parents = re.findall(r"\[\[(.+?)(?:\|.+?)?\]\]", m.group(1))
            if skill_name in parents:
                issues.append((fname, skill_name))
    return issues


def print_report(dup_groups, broken_links, self_refs):
    """Print full analysis report."""
    print("\n" + "=" * 60)
    print("SKILLS GRAPH CLEANUP REPORT")
    print("=" * 60)

    print(f"\n📁 Skills directory: {len(os.listdir(SKILLS_DIR))} files")

    # Duplicates
    print(f"\n🔁 DUPLICATE GROUPS ({len(dup_groups)} groups)")
    if dup_groups:
        for group in sorted(dup_groups, key=lambda g: normalize(g[0])):
            files_sorted = sorted(group, key=lambda f: (
                -_count_mentions(f),   # most mentions first
                -len(_read_about(f)),  # longest about second
                f                      # alphabetical last
            ))
            winner = files_sorted[0]
            losers = files_sorted[1:]
            print(f"  KEEP:   {winner}")
            for loser in losers:
                print(f"  REMOVE: {loser}")
    else:
        print("  ✅ No duplicates found")

    # Broken links
    total_broken = sum(len(v) for v in broken_links.values())
    fixable = sum(
        1 for v in broken_links.values()
        for item in v if item["suggestion"]
    )
    print(f"\n🔗 BROKEN LINKS ({total_broken} total, {fixable} auto-fixable)")
    for vac_fname, items in list(broken_links.items())[:20]:  # limit output
        print(f"\n  📄 {vac_fname}")
        for item in items:
            orig = item["original"]
            sug = item["suggestion"]
            if sug:
                print(f"    [[{orig}]] → [[{sug}|{orig}]]")
            else:
                print(f"    [[{orig}]] → ⚠️  no match found (manual fix needed)")
    if len(broken_links) > 20:
        print(f"\n  ... and {len(broken_links) - 20} more files")

    # Self-references
    print(f"\n🔄 SELF-REFERENCING PARENTS ({len(self_refs)} issues)")
    for fname, skill_name in self_refs[:10]:
        print(f"  {fname}: [[{skill_name}]] in own Parent section")
    if len(self_refs) > 10:
        print(f"  ... and {len(self_refs) - 10} more")

    print("\n" + "=" * 60)
    print("To apply all fixes: venv/bin/python merge_skills.py --apply")
    print("=" * 60 + "\n")


# ---------------------------------------------------------------------------
# Phase 2: Apply
# ---------------------------------------------------------------------------

def _read_about(fname: str) -> str:
    path = os.path.join(SKILLS_DIR, fname)
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"## About\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    return m.group(1).strip() if m else ""


def _count_mentions(fname: str) -> int:
    path = os.path.join(SKILLS_DIR, fname)
    if not os.path.exists(path):
        return 0
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"## Mentions\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    if not m:
        return 0
    return len(re.findall(r"\[\[", m.group(1)))


def _extract_section_links(content: str, section: str) -> list[str]:
    """Extract [[...]] links from a named ## Section."""
    m = re.search(rf"## {re.escape(section)}\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    if not m:
        return []
    return re.findall(r"\[\[(.+?)(?:\|.+?)?\]\]", m.group(1))


def backup_skills():
    """Create a timestamped backup of the Skills directory."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{BACKUP_DIR}_{ts}"
    shutil.copytree(SKILLS_DIR, dest)
    print(f"✅ Backup created: {dest}")
    return dest


def restore_latest_backup():
    """Restore the most recent backup."""
    backups = sorted([
        d for d in os.listdir(DATA_DIR)
        if d.startswith("skills_backup_")
    ])
    if not backups:
        print("❌ No backups found.")
        return
    latest = os.path.join(DATA_DIR, backups[-1])
    print(f"🔄 Restoring from: {latest}")
    if os.path.exists(SKILLS_DIR):
        shutil.rmtree(SKILLS_DIR)
    shutil.copytree(latest, SKILLS_DIR)
    print(f"✅ Restored successfully from {latest}")


def merge_duplicate_group(group: list[str]) -> str:
    """Merge a group of duplicate files into one winner. Returns winner filename."""
    files_sorted = sorted(group, key=lambda f: (
        -_count_mentions(f),
        -len(_read_about(f)),
        f
    ))
    winner_fname = files_sorted[0]
    loser_fnames = files_sorted[1:]
    winner_path = os.path.join(SKILLS_DIR, winner_fname)

    with open(winner_path, "r", encoding="utf-8") as f:
        winner_content = f.read()

    # Get winner skill name (for self-ref check)
    winner_name = os.path.splitext(winner_fname)[0]

    # Collect all mentions, parents, children from losers
    all_mentions = set(_extract_section_links(winner_content, "Mentions"))
    all_parents = set(_extract_section_links(winner_content, "Parent"))
    all_children = set(_extract_section_links(winner_content, "Children"))

    for loser_fname in loser_fnames:
        loser_path = os.path.join(SKILLS_DIR, loser_fname)
        if not os.path.exists(loser_path):
            continue
        with open(loser_path, "r", encoding="utf-8") as f:
            loser_content = f.read()
        all_mentions |= set(_extract_section_links(loser_content, "Mentions"))
        all_parents |= set(_extract_section_links(loser_content, "Parent"))
        all_children |= set(_extract_section_links(loser_content, "Children"))
        os.remove(loser_path)
        print(f"  🗑️  Removed: {loser_fname}")

    # Remove self-reference from parents
    all_parents.discard(winner_name)

    # Rebuild winner content with merged data
    winner_content = _rebuild_skill_sections(
        winner_content, all_mentions, all_parents, all_children
    )
    with open(winner_path, "w", encoding="utf-8") as f:
        f.write(winner_content)

    print(f"  ✅ Winner: {winner_fname} ({len(all_mentions)} mentions, "
          f"{len(all_parents)} parents, {len(all_children)} children)")
    return winner_fname


def _rebuild_skill_sections(
    content: str,
    mentions: set[str],
    parents: set[str],
    children: set[str],
) -> str:
    """Replace the Parent, Children, Mentions sections in a skill note."""
    def make_section(title: str, items: set[str], required=True) -> str:
        if not items and not required:
            return ""
        lines = sorted(f"- [[{item}]]" for item in items)
        if not lines:
            lines = ["- (none)"]
        return f"## {title}\n" + "\n".join(lines) + "\n"

    # Strip old sections
    for section in ["Parent", "Children", "Mentions"]:
        content = re.sub(
            rf"## {section}\n.*?(?=\n## |\Z)", "", content, flags=re.DOTALL
        )

    content = content.rstrip() + "\n\n"
    content += make_section("Parent", parents)
    if children:
        content += "\n" + make_section("Children", children, required=False)
    content += "\n" + make_section("Mentions", mentions, required=False)
    return content


def fix_broken_links_in_files(broken_links: dict[str, list[dict]], directory: str):
    """Replace broken [[X]] with [[Canonical|X]] in files within a directory."""
    fixed_count = 0
    for fname, items in broken_links.items():
        path = os.path.join(directory, fname)
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        changed = False
        for item in items:
            orig = item["original"]
            sug = item["suggestion"]
            if not sug:
                continue  # skip unresolvable links

            # Replace [[orig]] (not already aliased) with [[sug|orig]]
            if orig == sug:
                continue  # already correct

            old_link = f"[[{orig}]]"
            new_link = f"[[{sug}|{orig}]]"
            if old_link in content:
                content = content.replace(old_link, new_link)
                changed = True
                fixed_count += 1

        if changed:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

    label = os.path.basename(directory)
    print(f"  🔗 Fixed {fixed_count} broken links in {label}/")


def fix_stale_links_after_merge(merged_map: dict[str, str]):
    """After merging duplicates, fix all references to deleted losers.

    merged_map: {loser_name: winner_name} for all deleted duplicates.
    Scans both Vacancies/ and Skills/ directories.
    """
    total_fixed = 0
    for directory in [VACANCIES_DIR, SKILLS_DIR]:
        for fname in os.listdir(directory):
            if not fname.endswith(".md"):
                continue
            path = os.path.join(directory, fname)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

            changed = False
            for loser, winner in merged_map.items():
                old_link = f"[[{loser}]]"
                if old_link in content:
                    new_link = f"[[{winner}|{loser}]]" if loser != winner else f"[[{winner}]]"
                    content = content.replace(old_link, new_link)
                    changed = True
                    total_fixed += 1
                # Also fix alias links [[loser|something]]
                old_alias = f"[[{loser}|"
                if old_alias in content:
                    content = content.replace(old_alias, f"[[{winner}|")
                    changed = True
                    total_fixed += 1

            if changed:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)

    print(f"  🔗 Fixed {total_fixed} stale links to merged duplicates")


def fix_self_references(self_refs: list[tuple[str, str]]):
    """Remove self-referencing links from Parent sections."""
    fixed = 0
    for fname, skill_name in self_refs:
        path = os.path.join(SKILLS_DIR, fname)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        def remove_self_link(m):
            section_content = m.group(1)
            # Remove lines containing [[skill_name]]
            lines = section_content.split("\n")
            lines = [l for l in lines if f"[[{skill_name}]]" not in l]
            return "## Parent\n" + "\n".join(lines)

        new_content = re.sub(
            r"## Parent\n(.+?)(?=\n##|\Z)",
            remove_self_link,
            content,
            flags=re.DOTALL
        )
        if new_content != content:
            with open(path, "w", encoding="utf-8") as f:
                f.write(new_content)
            fixed += 1

    print(f"  🔄 Fixed {fixed} self-referencing Parent entries")


def rebuild_graph():
    """Rebuild skills_graph.json from current Skills/ files."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("seed_graph", "seed_graph.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.main()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    apply = "--apply" in sys.argv
    backup_only = "--backup-only" in sys.argv
    restore = "--restore" in sys.argv

    if restore:
        restore_latest_backup()
        return

    print("\n🔍 Analyzing Skills graph...")
    index = build_skills_index()
    dup_groups = find_duplicate_groups(index)
    broken_links = find_broken_links(index)
    self_refs = find_self_references()

    print_report(dup_groups, broken_links, self_refs)

    if not apply:
        print("ℹ️  This was a dry run. No files were modified.")
        print("   Run with --apply to apply all fixes.\n")
        return

    if backup_only:
        backup_skills()
        print("ℹ️  Backup-only mode — no fixes applied.\n")
        return

    # --- Apply phase ---
    print("\n🚀 Applying fixes...\n")
    backup_path = backup_skills()
    print()

    # Step 1: Merge duplicates
    merged_map: dict[str, str] = {}  # loser_name → winner_name
    print(f"Step 1: Merging {len(dup_groups)} duplicate groups...")
    for group in dup_groups:
        winner_fname = merge_duplicate_group(group)
        winner_name = os.path.splitext(winner_fname)[0]
        for f in group:
            loser_name = os.path.splitext(f)[0]
            if loser_name != winner_name:
                merged_map[loser_name] = winner_name

    # Step 1b: Fix stale links to deleted duplicates
    if merged_map:
        print(f"\nStep 1b: Fixing stale links to {len(merged_map)} merged duplicates...")
        fix_stale_links_after_merge(merged_map)

    # Step 2: Fix broken links in vacancies
    print(f"\nStep 2: Fixing broken links in vacancies...")
    # Rebuild index after merges
    index = build_skills_index()
    broken_links = find_broken_links(index)
    fix_broken_links_in_files(broken_links, VACANCIES_DIR)

    # Step 3: Fix self-references
    print(f"\nStep 3: Fixing self-referencing Parents...")
    self_refs = find_self_references()
    fix_self_references(self_refs)

    # Step 4: Rebuild graph
    print(f"\nStep 4: Rebuilding skills_graph.json...")
    rebuild_graph()

    print("\n✅ All done! Backup available at:", backup_path)
    print("   To undo: venv/bin/python merge_skills.py --restore\n")


if __name__ == "__main__":
    main()
