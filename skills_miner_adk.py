"""
skills_miner_adk.py — Two-agent Skills Miner powered by Google ADK.

Agent 1 (Extractor): Reads a vacancy, extracts skills as structured JSON.
Agent 2 (Reviewer): Validates against graph context, normalizes via synonyms.
Python tools layer: Applies approved changes to Obsidian vault files.

Usage:
    venv/bin/python skills_miner_adk.py                   # process all
    venv/bin/python skills_miner_adk.py --limit 5          # test on 5
    venv/bin/python skills_miner_adk.py --dry-run          # preview only
    venv/bin/python skills_miner_adk.py --concurrency 3    # parallel workers (default 3)
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.genai import types

import skills_tools

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "gemini-2.5-flash-lite"
CONCURRENCY = 3        # parallel LLM extraction workers
MAX_RETRIES = 3        # JSON parse retries per agent call
RETRY_BASE_DELAY = 2   # seconds, doubles each retry

CHECKPOINTS_DIR = os.path.join("data", "checkpoints")

# ---------------------------------------------------------------------------
# Agent instructions
# ---------------------------------------------------------------------------

EXTRACTOR_INSTRUCTION = """You are a Skills Extractor agent. Your job is to read a job vacancy description and extract all technical skills, tools, technologies, frameworks, platforms, and methodologies mentioned in the text.

RULES:
1. Extract skills EXACTLY as they appear in the text (preserve original form: "K8s", "AWS", "Terraform", etc.)
2. Only extract real technical skills, tools, technologies, platforms, frameworks, methodologies, certifications.
3. Do NOT extract soft skills (e.g., "teamwork", "communication", "leadership").
4. Do NOT extract generic terms (e.g., "experience", "knowledge", "years", "team", "projects").
5. Do NOT extract job titles or roles as skills (e.g., "DevOps Engineer" is NOT a skill, but "DevOps" IS).
6. Do NOT extract company names, locations, or benefits.
7. For each skill, suggest a parent category (e.g., "Docker" → "Containers", "AWS" → "Cloud platforms").
8. Provide a brief 1-sentence "about" description for each skill.

You will receive the vacancy content. Respond with a JSON array ONLY, no markdown fences, no explanation:

[
  {"skill": "K8s", "context_line": "experience with K8s orchestration", "about": "Container orchestration platform", "suggested_parent": "Containers", "tags": ["containers", "orchestration"]},
  ...
]

If no skills are found, return: []
"""

REVIEWER_INSTRUCTION = """You are a Skills Reviewer agent. You receive:
1. A list of extracted skills from Agent 1
2. The current graph state (existing skills and their hierarchy)
3. The synonym dictionary

Your job is to validate, normalize, and approve the extracted skills.

RULES:
1. Map skill names to their CANONICAL form using the synonym dictionary.
   Example: if synonym has "K8s" → "Kubernetes", then canonical = "Kubernetes", original = "K8s"
2. If a skill already exists in the graph, reuse its exact name and hierarchy.
3. Validate parent-child relationships. Common hierarchy:
   - Cloud platforms → AWS, GCP, Azure
   - AWS → EC2, RDS, MSK, EKS, ECS, Lambda, S3, CloudFormation
   - GCP → GKE, Cloud Run, BigQuery
   - Azure → AKS, Azure DevOps
   - Containers → Docker, Kubernetes
   - Kubernetes → GKE, EKS, AKS
   - DevOps → CI/CD, IaC, SRE, GitOps
   - IaC → Terraform, Pulumi, CloudFormation
   - CI/CD → Jenkins, GitHub Actions, GitLab CI, ArgoCD
   - Programming languages → Python, Java, JavaScript, PHP, Golang
   - Databases → PostgreSQL, MySQL, MongoDB, ClickHouse, Cassandra, Elasticsearch
4. Remove any false positives (non-technical terms, company names, etc.)
5. If you detect a NEW synonym that should be added (e.g., a skill appears as abbreviation), include it in new_synonyms.
6. Set children to [] unless you KNOW the skill has sub-skills that are also extracted.

Respond with a JSON object ONLY, no markdown fences, no explanation:

{
  "approved_skills": [
    {"original": "K8s", "canonical": "Kubernetes", "about": "...", "parent": ["Containers"], "children": [], "tags": ["containers", "orchestration"]}
  ],
  "rejected_skills": [
    {"skill": "teamwork", "reason": "soft skill"}
  ],
  "new_synonyms": [
    {"abbreviation": "K8s", "canonical": "Kubernetes"}
  ]
}
"""


# ---------------------------------------------------------------------------
# Agent setup
# ---------------------------------------------------------------------------

def create_agents():
    """Creates the two ADK agents."""
    extractor = Agent(
        name="skills_extractor",
        model=MODEL,
        instruction=EXTRACTOR_INSTRUCTION,
        description="Extracts technical skills from job vacancy text.",
    )

    reviewer = Agent(
        name="skills_reviewer",
        model=MODEL,
        instruction=REVIEWER_INSTRUCTION,
        description="Validates and normalizes extracted skills against the knowledge graph.",
    )

    return extractor, reviewer


# ---------------------------------------------------------------------------
# Pipeline logic
# ---------------------------------------------------------------------------

async def run_agent_once(runner: InMemoryRunner, message: str, user_id: str, session_id: str) -> str:
    """Sends a single message to an agent and collects the text response."""
    # Ensure session exists
    session = await runner.session_service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=session_id
    )
    if not session:
        session = await runner.session_service.create_session(
            app_name=runner.app_name, user_id=user_id, session_id=session_id
        )

    response_parts = []
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(
            role="user",
            parts=[types.Part(text=message)]
        ),
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if part.text:
                    response_parts.append(part.text)
    return "".join(response_parts)



def _strip_fences(text: str) -> str:
    """Remove markdown code fences from LLM response."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


def parse_json_response(text: str) -> any:
    """Parse JSON from LLM response, handling markdown fences."""
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON parse error: {e}")
        print(f"  Raw response: {text[:300]}...")
        return None


async def run_agent_with_retry(
    runner: InMemoryRunner,
    message: str,
    user_id: str,
    session_id: str,
    expected_type: type,
) -> any:
    """Run agent and retry up to MAX_RETRIES times if JSON is invalid."""
    for attempt in range(MAX_RETRIES):
        raw = await run_agent_once(runner, message, user_id, session_id)
        parsed = parse_json_response(raw)
        if parsed is not None and isinstance(parsed, expected_type):
            return parsed
        if attempt < MAX_RETRIES - 1:
            delay = RETRY_BASE_DELAY * (2 ** attempt)
            print(f"  ⚠️  Retry {attempt + 1}/{MAX_RETRIES - 1} in {delay}s...")
            await asyncio.sleep(delay)
    return None


# ---------------------------------------------------------------------------
# Checkpoints — persist extraction results for resume on crash
# ---------------------------------------------------------------------------

def _checkpoint_path(filename: str) -> str:
    os.makedirs(CHECKPOINTS_DIR, exist_ok=True)
    return os.path.join(CHECKPOINTS_DIR, filename.replace(".md", ".json"))


def save_checkpoint(filename: str, approved: list, new_synonyms: list):
    with open(_checkpoint_path(filename), "w", encoding="utf-8") as f:
        json.dump({"approved": approved, "new_synonyms": new_synonyms}, f, ensure_ascii=False)


def load_checkpoint(filename: str) -> tuple[list, list] | None:
    path = _checkpoint_path(filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("approved", []), data.get("new_synonyms", [])
    return None


def clear_checkpoint(filename: str):
    path = _checkpoint_path(filename)
    if os.path.exists(path):
        os.remove(path)


async def extract_vacancy(
    filename: str,
    extractor_runner: InMemoryRunner,
    reviewer_runner: InMemoryRunner,
    semaphore: asyncio.Semaphore,
) -> tuple[str, list, list] | None:
    """Phase 1 (parallelizable): LLM extraction only. Returns (filename, approved, new_synonyms)."""
    async with semaphore:
        # Check checkpoint first — resume after crash
        cached = load_checkpoint(filename)
        if cached is not None:
            approved, new_synonyms = cached
            print(f"  ♻️  [{filename}] Resuming from checkpoint ({len(approved)} skills)")
            return filename, approved, new_synonyms

        print(f"\n  🔍 [{filename}] Agent 1: extracting...")
        content = skills_tools.read_vacancy(filename)
        if content.startswith("ERROR"):
            print(f"  ❌ [{filename}] {content}")
            return None

        extracted = await run_agent_with_retry(
            extractor_runner,
            f"Extract skills from this vacancy:\n\n{content}",
            user_id="miner",
            session_id=f"extract_{filename}",
            expected_type=list,
        )
        if extracted is None:
            print(f"  ❌ [{filename}] Extractor failed after {MAX_RETRIES} retries")
            return None

        if not extracted:
            return filename, [], []

        print(f"  🧠 [{filename}] Agent 2: reviewing {len(extracted)} skills...")
        # Send compact graph (names only) + synonyms for reviewer context
        graph_names = json.loads(skills_tools.get_graph_state())
        synonyms = json.loads(skills_tools.get_synonyms())

        reviewer_message = json.dumps({
            "extracted_skills": extracted,
            "existing_skill_names": graph_names,
            "synonyms": synonyms,
        }, ensure_ascii=False)

        reviewed = await run_agent_with_retry(
            reviewer_runner,
            f"Review these extracted skills:\n\n{reviewer_message}",
            user_id="miner",
            session_id=f"review_{filename}",
            expected_type=dict,
        )
        if reviewed is None:
            print(f"  ❌ [{filename}] Reviewer failed after {MAX_RETRIES} retries")
            return None

        approved = reviewed.get("approved_skills", [])
        new_synonyms = reviewed.get("new_synonyms", [])
        rejected = reviewed.get("rejected_skills", [])

        print(f"  ✅ [{filename}] Approved: {len(approved)} | Rejected: {len(rejected)}")
        save_checkpoint(filename, approved, new_synonyms)
        return filename, approved, new_synonyms


def apply_vacancy_results(
    filename: str,
    approved: list,
    new_synonyms: list,
    dry_run: bool,
    idx: int,
    total: int,
) -> bool:
    """Phase 2 (sequential): apply LLM results to vault files."""
    print(f"\n[{idx}/{total}] 📝 Applying: {filename}")

    if dry_run:
        for skill in approved:
            print(f"     DRY: '{skill['original']}' → [[{skill['canonical']}]]")
        return True

    if not approved:
        skills_tools.mark_processed(filename)
        return True

    # Insert wikilinks into vacancy
    replacements = [{"original": s["original"], "canonical": s["canonical"]} for s in approved]
    print(f"     {skills_tools.insert_wikilinks(filename, replacements)}")

    # Create/update skill notes
    for skill in approved:
        result = skills_tools.upsert_skill(
            name=skill["canonical"],
            about=skill.get("about", ""),
            tags=skill.get("tags", []),
            parent=skill.get("parent", []),
            children=skill.get("children", []),
            vacancy_filename=filename,
        )
        print(f"     {result}")

    # Add new synonyms
    for syn in new_synonyms:
        abbrev, canon = syn.get("abbreviation"), syn.get("canonical")
        if abbrev and canon:
            print(f"     {skills_tools.add_synonym(abbrev, canon)}")

    skills_tools.mark_processed(filename)
    clear_checkpoint(filename)
    print(f"     ✅ Done")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    # Parse CLI args
    limit = 0
    dry_run = False
    concurrency = CONCURRENCY
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2
        elif arg.startswith("--limit="):
            limit = int(arg.split("=")[1]); i += 1
        elif arg == "--concurrency" and i + 1 < len(args):
            concurrency = int(args[i + 1]); i += 2
        elif arg.startswith("--concurrency="):
            concurrency = int(arg.split("=")[1]); i += 1
        elif arg == "--dry-run":
            dry_run = True; i += 1
        else:
            i += 1

    if not os.environ.get("GOOGLE_API_KEY"):
        print("❌ GOOGLE_API_KEY not set. Create a .env file or export it.")
        sys.exit(1)

    unprocessed = skills_tools.list_unprocessed_vacancies()
    total = len(unprocessed)
    print(f"\n📊 Total unprocessed vacancies: {total}")

    if limit:
        unprocessed = unprocessed[:limit]
        print(f"   Limit: {limit}")
    if dry_run:
        print("   Mode: DRY RUN (no files will be modified)")
    print(f"   Concurrency: {concurrency} parallel workers")

    if not unprocessed:
        print("   ✅ All vacancies already processed!")
        return

    extractor, reviewer = create_agents()
    extractor_runner = InMemoryRunner(agent=extractor, app_name="skills_miner_extractor")
    reviewer_runner = InMemoryRunner(agent=reviewer, app_name="skills_miner_reviewer")

    # Phase 1: parallel LLM extraction
    print(f"\n🔍 Phase 1: Extracting skills from {len(unprocessed)} vacancies...")
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        extract_vacancy(f, extractor_runner, reviewer_runner, semaphore)
        for f in unprocessed
    ]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Phase 2: sequential apply (safe file writes, no concurrent graph corruption)
    print(f"\n📝 Phase 2: Applying results to vault...")
    success = failed = 0
    for idx, result in enumerate(raw_results, 1):
        if isinstance(result, Exception):
            print(f"  ❌ [{unprocessed[idx-1]}] Exception: {result}")
            failed += 1
            continue
        if result is None:
            failed += 1
            continue
        filename, approved, new_synonyms = result
        try:
            ok = apply_vacancy_results(filename, approved, new_synonyms, dry_run, idx, len(unprocessed))
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ Error applying {filename}: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"📊 Summary: {success} succeeded, {failed} failed out of {len(unprocessed)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
