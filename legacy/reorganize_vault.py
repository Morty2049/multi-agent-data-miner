"""
reorganize_vault.py — LLM-based Skills vault reorganization.

Uses Gemini to:
  1. Group semantically equivalent skills (K8s = Kubernetes, CI_CD = CI/CD)
  2. Assign canonical names and cluster tags to each skill
  3. Build a 3-level hierarchy

The results are saved to data/reorganize_manifest.json for inspection before
any files are touched. Then --apply merges skill files and updates wikilinks
in both Skills/ and Vacancies/ — vacancy text is never modified, only wikilinks.

Usage:
    venv/bin/python reorganize_vault.py --analyze          # generate manifest
    venv/bin/python reorganize_vault.py --apply            # apply saved manifest
    venv/bin/python reorganize_vault.py --verify           # check broken links
    venv/bin/python reorganize_vault.py --analyze --apply  # analyze + apply in one run
"""

import json
import os
import re
import shutil
import sys
import time
from collections import defaultdict
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

VAULT_BASE = "obsidian_vault"
SKILLS_DIR = os.path.join(VAULT_BASE, "Skills")
VACANCIES_DIR = os.path.join(VAULT_BASE, "Vacancies")
DATA_DIR = "data"
MANIFEST_PATH = os.path.join(DATA_DIR, "reorganize_manifest.json")
BACKUP_DIR = os.path.join(DATA_DIR, "vault_backup")

MODEL = "gemini-2.5-flash-lite"
BATCH_SIZE = 120      # skill names per LLM call
DELAY_BETWEEN_BATCHES = 2.0   # seconds, rate limiting

# Canonical cluster tags the LLM should use
CLUSTER_TAGS = [
    "#cloud", "#containers", "#devops", "#ci-cd", "#iac",
    "#backend", "#frontend", "#databases", "#data-engineering",
    "#ai-ml", "#security", "#networking", "#mobile",
    "#management", "#certifications", "#testing", "#observability",
    "#programming", "#messaging", "#api",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: str, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default if default is not None else {}


def _save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_all_skill_names() -> list[str]:
    return sorted(
        fname[:-3] for fname in os.listdir(SKILLS_DIR) if fname.endswith(".md")
    )


def _read_skill_file(name: str) -> str:
    path = os.path.join(SKILLS_DIR, f"{name}.md")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _count_mentions(name: str) -> int:
    content = _read_skill_file(name)
    m = re.search(r"## Mentions\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    return len(re.findall(r"\[\[", m.group(1))) if m else 0


def extract_wikilinks(content: str) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)]


# ---------------------------------------------------------------------------
# Phase 1: Analyze — call Gemini to build skill_map
# ---------------------------------------------------------------------------

ANALYZE_PROMPT = """You are a technical skills taxonomy expert.

I will give you a list of skill names from an Obsidian knowledge graph built from job vacancies.
Your task is to normalize and cluster them.

For EACH skill name in the input list, return a JSON entry with:
- "canonical": the single best canonical name for this skill (e.g. "K8s" → "Kubernetes", "CI_CD" → "CI/CD", "Programming languages" → "Programming Languages")
- "tags": 1-3 cluster tags from this exact list: {tags}

Rules:
1. If a skill is clearly an alias/variant of another in the list → set canonical to the proper form
2. Preserve names that are already correct (e.g. "Python" → "Python")
3. Fix casing: use Title Case for multi-word skills ("programming languages" → "Programming Languages")
4. Fix separators: underscores → spaces or slash where appropriate ("CI_CD" → "CI/CD", "AI_ML" → "AI/ML")
5. Do NOT merge skills that are genuinely different concepts
6. Certifications like "AWS Solutions Architect" keep their full name
7. Tags must come ONLY from the provided list

Respond with a JSON object mapping each input name to its entry. No markdown, no explanation.
Example:
{{
  "K8s": {{"canonical": "Kubernetes", "tags": ["#containers", "#devops"]}},
  "kubernetes": {{"canonical": "Kubernetes", "tags": ["#containers", "#devops"]}},
  "Python": {{"canonical": "Python", "tags": ["#backend", "#programming"]}},
  "CI_CD": {{"canonical": "CI/CD", "tags": ["#devops", "#ci-cd"]}}
}}

Input skill names:
{names}
"""


def analyze_batch(client: genai.Client, names: list[str]) -> dict:
    """Call Gemini on a batch of skill names. Returns partial skill_map."""
    prompt = ANALYZE_PROMPT.format(
        tags=", ".join(CLUSTER_TAGS),
        names=json.dumps(names, ensure_ascii=False),
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.1),
    )
    text = response.text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        result = json.loads(text)
        # Validate: each value must have canonical and tags
        valid = {}
        for name, entry in result.items():
            if isinstance(entry, dict) and "canonical" in entry and "tags" in entry:
                valid[name] = entry
            else:
                # Fallback: keep as-is
                valid[name] = {"canonical": name, "tags": []}
        return valid
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON parse error in batch: {e}")
        print(f"  Raw: {text[:300]}...")
        # Fallback: identity mapping for this batch
        return {name: {"canonical": name, "tags": []} for name in names}


def build_manifest(all_names: list[str]) -> dict:
    """Call Gemini in batches, assemble full skill_map, save manifest."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY not set.")
        sys.exit(1)

    client = genai.Client(api_key=api_key)

    batches = [all_names[i:i + BATCH_SIZE] for i in range(0, len(all_names), BATCH_SIZE)]
    print(f"  Processing {len(all_names)} skills in {len(batches)} batches of ~{BATCH_SIZE}...")

    skill_map: dict[str, dict] = {}

    for idx, batch in enumerate(batches, 1):
        print(f"  Batch {idx}/{len(batches)} ({len(batch)} skills)...", end=" ", flush=True)
        result = analyze_batch(client, batch)
        skill_map.update(result)
        print(f"✅ ({len(result)} entries)")
        if idx < len(batches):
            time.sleep(DELAY_BETWEEN_BATCHES)

    manifest = {"skill_map": skill_map, "generated_at": datetime.now().isoformat()}
    _save_json(MANIFEST_PATH, manifest)
    print(f"\n  💾 Manifest saved: {MANIFEST_PATH}")
    return manifest


# ---------------------------------------------------------------------------
# Phase 2: Apply manifest
# ---------------------------------------------------------------------------

def _backup_vault():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = f"{BACKUP_DIR}_{ts}"
    shutil.copytree(VAULT_BASE, dest)
    print(f"  ✅ Backup: {dest}")
    return dest


def _update_tags_in_file(path: str, tags: list[str]):
    """Add cluster tags to skill file frontmatter."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    # Find existing tags line in frontmatter
    def replace_tags(m):
        existing_raw = m.group(1)
        # Parse existing tags (strip brackets and split)
        existing = re.findall(r"[\w#\-/\.]+", existing_raw)
        # Remove old cluster tags (start with #)
        existing = [t for t in existing if not t.startswith("#")]
        merged = existing + [t for t in tags if t not in existing]
        return f"tags: [{', '.join(merged)}]"

    new_content = re.sub(r"tags:\s*\[([^\]]*)\]", replace_tags, content, count=1)
    if new_content != content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)


def _safe_filename(name: str) -> str:
    """Convert canonical display name to filesystem-safe filename stem."""
    return re.sub(r'[/\\:*?"<>|]', "_", name)


def _add_alias_to_file(path: str, alias: str):
    """Add `aliases: [alias]` to frontmatter and set h1 title to display name."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    # Add/update aliases in frontmatter
    if f"aliases:" not in content:
        content = re.sub(r"(---\n)", rf"\1aliases: [{alias}]\n", content, count=1)
    # Update h1 title if it differs from alias
    content = re.sub(r"^# .+$", f"# {alias}", content, count=1, flags=re.MULTILINE)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _replace_wikilinks_in_file(path: str, rename_map: dict[str, str]):
    """Replace [[old]] → [[canonical|old]] in a file. Returns number of replacements."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    for old, canonical in rename_map.items():
        if old == canonical:
            continue
        # Replace [[old]] → [[canonical|old]]
        content = content.replace(f"[[{old}]]", f"[[{canonical}|{old}]]")
        # Update target of alias links [[old|display]] → [[canonical|display]]
        content = re.sub(
            r"\[\[" + re.escape(old) + r"\|([^\]]+)\]\]",
            lambda m: f"[[{canonical}|{m.group(1)}]]",
            content,
        )

    if content != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return content.count("[[") - original.count("[[")  # rough delta
    return 0


def _strip_wikilinks_in_file(path: str, dead_names: set[str]):
    """Remove [[dead_skill]] wikilinks from a file (replace with plain text display)."""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    original = content
    for name in dead_names:
        # [[name]] → name  (keep display text, remove link)
        content = content.replace(f"[[{name}]]", name)
        # [[name|display]] → display
        content = re.sub(r"\[\[" + re.escape(name) + r"\|([^\]]+)\]\]", r"\1", content)
    if content != original:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def apply_manifest(manifest: dict):
    """Apply skill_map: merge duplicate files, update wikilinks, add cluster tags."""
    skill_map: dict[str, dict] = manifest.get("skill_map", {})
    if not skill_map:
        print("❌ Empty manifest. Run --analyze first.")
        return

    _backup_vault()

    # ── Step 0: Handle deletions ──────────────────────────────────────────
    to_delete = {
        name for name, entry in skill_map.items()
        if entry.get("canonical") == "__DELETE__"
    }
    existing_names = set(load_all_skill_names())
    if to_delete:
        print(f"\n  Step 0: Deleting {len(to_delete)} obsolete skill files...")
        deleted = 0
        for name in sorted(to_delete):
            if name not in existing_names:
                continue
            skill_path = os.path.join(SKILLS_DIR, f"{name}.md")
            os.remove(skill_path)
            deleted += 1
            print(f"     🗑️  Deleted: {name}")
        # Strip wikilinks to deleted skills from all files
        for directory in [VACANCIES_DIR, SKILLS_DIR]:
            for fname in os.listdir(directory):
                if fname.endswith(".md"):
                    _strip_wikilinks_in_file(os.path.join(directory, fname), to_delete)
        print(f"     Deleted {deleted} files, stripped wikilinks from vault")
        # Remove deleted names from existing_names
        existing_names -= to_delete
        # Remove from skill_map so they don't affect rename logic
        for name in to_delete:
            skill_map.pop(name, None)

    # Build: canonical → list of member names (files to merge into canonical)
    canonical_to_members: dict[str, list[str]] = defaultdict(list)
    for name, entry in skill_map.items():
        canonical = entry.get("canonical", name)
        if canonical != "__DELETE__":
            canonical_to_members[canonical].append(name)

    # Build rename map for wikilink updates: old_name → safe_canonical
    # Wikilinks must use the filesystem-safe name (e.g. CI_CD not CI/CD)
    rename_map: dict[str, str] = {}
    for name, entry in skill_map.items():
        canonical = entry.get("canonical", name)
        if canonical == "__DELETE__":
            continue
        safe = _safe_filename(canonical)
        if name != safe:
            rename_map[name] = safe

    merged_count = 0
    renamed_count = 0

    print(f"\n  Step 1: Merging {len(canonical_to_members)} canonical skill groups...")

    for canonical, members in canonical_to_members.items():
        # Filter to members that actually have files
        real_members = [m for m in members if m in existing_names]
        if not real_members:
            continue

        # Filesystem-safe filename: replace / and other unsafe chars with _
        safe_name = _safe_filename(canonical)
        canonical_path = os.path.join(SKILLS_DIR, f"{safe_name}.md")
        needs_alias = safe_name != canonical  # canonical display name differs from filename

        # Determine winner: member with most mentions
        winner = max(real_members, key=_count_mentions)
        winner_path = os.path.join(SKILLS_DIR, f"{_safe_filename(winner)}.md")

        # If safe canonical name differs from winner's safe filename, rename winner
        if _safe_filename(winner) != safe_name and os.path.exists(winner_path):
            os.rename(winner_path, canonical_path)
            renamed_count += 1

        # Merge all other members into canonical
        losers = [m for m in real_members if m != winner]
        if losers:
            if os.path.exists(canonical_path):
                with open(canonical_path, "r", encoding="utf-8") as f:
                    winner_content = f.read()
            else:
                winner_content = ""

            all_mentions = set(re.findall(r"\[\[([^\]|]+)\]\]", _section(winner_content, "Mentions")))
            all_parents = set(re.findall(r"\[\[([^\]|]+)\]\]", _section(winner_content, "Parent")))
            all_children = set(re.findall(r"\[\[([^\]|]+)\]\]", _section(winner_content, "Children")))

            for loser in losers:
                loser_path = os.path.join(SKILLS_DIR, f"{_safe_filename(loser)}.md")
                if not os.path.exists(loser_path):
                    continue
                loser_content = _read_skill_file(loser)
                all_mentions |= set(re.findall(r"\[\[([^\]|]+)\]\]", _section(loser_content, "Mentions")))
                all_parents |= set(re.findall(r"\[\[([^\]|]+)\]\]", _section(loser_content, "Parent")))
                all_children |= set(re.findall(r"\[\[([^\]|]+)\]\]", _section(loser_content, "Children")))
                os.remove(loser_path)
                merged_count += 1

            all_parents.discard(canonical)
            all_parents.discard(safe_name)
            all_children.discard(canonical)
            all_children.discard(safe_name)

            if os.path.exists(canonical_path):
                winner_content = _rebuild_sections(winner_content, all_mentions, all_parents, all_children)
                with open(canonical_path, "w", encoding="utf-8") as f:
                    f.write(winner_content)

        # Add alias if display name != filename (e.g. file is CI_CD.md, alias is CI/CD)
        if needs_alias and os.path.exists(canonical_path):
            _add_alias_to_file(canonical_path, canonical)

        # Update cluster tags
        tags = skill_map.get(winner, skill_map.get(canonical, {})).get("tags", [])
        if tags and os.path.exists(canonical_path):
            _update_tags_in_file(canonical_path, tags)

    print(f"     Merged {merged_count} duplicate files, renamed {renamed_count} files")

    # Step 2: Update wikilinks in all files
    print(f"  Step 2: Updating wikilinks in Skills/ and Vacancies/...")
    skills_fixed = vacancies_fixed = 0

    for fname in os.listdir(SKILLS_DIR):
        if fname.endswith(".md"):
            _replace_wikilinks_in_file(os.path.join(SKILLS_DIR, fname), rename_map)
            skills_fixed += 1

    for fname in os.listdir(VACANCIES_DIR):
        if fname.endswith(".md"):
            _replace_wikilinks_in_file(os.path.join(VACANCIES_DIR, fname), rename_map)
            vacancies_fixed += 1

    print(f"     Scanned {skills_fixed} skill files, {vacancies_fixed} vacancy files")

    print(f"\n  ✅ Apply complete.")


def _section(content: str, title: str) -> str:
    """Extract text content of a named ## Section."""
    m = re.search(rf"## {re.escape(title)}\n(.+?)(?=\n##|\Z)", content, re.DOTALL)
    return m.group(1) if m else ""


def _rebuild_sections(content: str, mentions: set, parents: set, children: set) -> str:
    """Replace Parent / Children / Mentions sections in skill note content."""
    def make_section(title: str, items: set, required=True) -> str:
        if not items and not required:
            return ""
        lines = sorted(f"- [[{item}]]" for item in items)
        return f"## {title}\n" + ("\n".join(lines) or "- (none)") + "\n"

    for section in ["Parent", "Children", "Mentions"]:
        content = re.sub(rf"## {section}\n.*?(?=\n## |\Z)", "", content, flags=re.DOTALL)

    content = content.rstrip() + "\n\n"
    content += make_section("Parent", parents)
    if children:
        content += "\n" + make_section("Children", children, required=False)
    content += "\n" + make_section("Mentions", mentions, required=False)
    return content


# ---------------------------------------------------------------------------
# Phase 3: Verify
# ---------------------------------------------------------------------------

def verify():
    """Count broken wikilinks remaining in vacancies and skills.

    Cross-directory links (vacancy mentions in skill files, company links in
    vacancy files) are excluded from the broken count — only same-domain links
    are validated.
    """
    skills = {f[:-3] for f in os.listdir(SKILLS_DIR) if f.endswith(".md")}
    vacancies = {f[:-3] for f in os.listdir(VACANCIES_DIR) if f.endswith(".md")}
    companies = (
        {f[:-3] for f in os.listdir(os.path.join(VAULT_BASE, "Companies")) if f.endswith(".md")}
        if os.path.isdir(os.path.join(VAULT_BASE, "Companies"))
        else set()
    )
    all_known = skills | vacancies | companies

    total_links = broken = 0
    broken_samples: list[tuple[str, str]] = []

    for directory, label in [(VACANCIES_DIR, "Vacancies"), (SKILLS_DIR, "Skills")]:
        dir_total = dir_broken = 0
        for fname in sorted(os.listdir(directory)):
            if not fname.endswith(".md"):
                continue
            with open(os.path.join(directory, fname), "r", encoding="utf-8") as f:
                content = f.read()
            links = extract_wikilinks(content)
            for link in links:
                # Skip links that resolve in ANY known directory
                if link in all_known:
                    dir_total += 1
                    continue
                dir_total += 1
                dir_broken += 1
                if len(broken_samples) < 20:
                    broken_samples.append((fname, link))
        total_links += dir_total
        broken += dir_broken
        print(f"  {label}: {dir_broken}/{dir_total} broken skill links")

    pct = (broken / total_links * 100) if total_links else 0
    print(f"\n  Total: {broken}/{total_links} broken ({pct:.1f}%)")
    if broken_samples:
        print("  Sample broken links:")
        for fname, link in broken_samples[:10]:
            print(f"    {fname[:50]}: [[{link}]]")
    if pct < 2:
        print("  ✅ Graph is healthy")
    elif pct < 10:
        print("  ⚠️  Some broken links remain")
    else:
        print("  ❌ Many broken links — re-run --analyze --apply")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = set(sys.argv[1:])
    do_analyze = "--analyze" in args
    do_apply = "--apply" in args
    do_verify = "--verify" in args

    if not any([do_analyze, do_apply, do_verify]):
        print(__doc__)
        sys.exit(0)

    print("\n🔧 Skills Vault Reorganizer")

    if do_analyze:
        print("\n📊 Phase 1: Analyzing skills with LLM...")
        all_names = load_all_skill_names()
        print(f"  Found {len(all_names)} skill files")
        manifest = build_manifest(all_names)

        # Print summary
        skill_map = manifest["skill_map"]
        renames = {k: v["canonical"] for k, v in skill_map.items() if v["canonical"] != k}
        print(f"\n  Summary:")
        print(f"  - Total skills analyzed: {len(skill_map)}")
        print(f"  - Renames/merges suggested: {len(renames)}")
        if renames:
            for old, new in list(renames.items())[:10]:
                print(f"    '{old}' → '{new}'")
            if len(renames) > 10:
                print(f"    ... and {len(renames) - 10} more (see {MANIFEST_PATH})")
        print(f"\n  Inspect {MANIFEST_PATH} before applying.\n")

    if do_apply:
        manifest = _load_json(MANIFEST_PATH)
        if not manifest:
            print("❌ No manifest found. Run --analyze first.")
            sys.exit(1)
        print(f"\n📝 Phase 2: Applying manifest...")
        print(f"  Generated at: {manifest.get('generated_at', 'unknown')}")
        apply_manifest(manifest)

    if do_verify:
        print("\n🔍 Phase 3: Verifying vault integrity...")
        verify()

    print("\n✅ Done.\n")


if __name__ == "__main__":
    main()
