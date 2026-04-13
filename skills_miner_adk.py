"""
skills_miner_adk.py — Two-agent Skills Miner powered by Google ADK.

Agent 1 (Extractor): Reads a vacancy, extracts skills as structured JSON.
Agent 2 (Reviewer): Validates against graph context, normalizes via synonyms.
Python tools layer: Applies approved changes to Obsidian vault files.

Usage:
    venv/bin/python skills_miner_adk.py                   # process all
    venv/bin/python skills_miner_adk.py --limit 5          # test on 5
    venv/bin/python skills_miner_adk.py --dry-run          # preview only
"""
import asyncio
import json
import os
import sys
import time

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
DELAY_BETWEEN_VACANCIES = 1.5  # seconds, for rate limiting

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



def parse_json_response(text: str) -> any:
    """Parse JSON from LLM response, handling markdown fences."""
    text = text.strip()
    # Remove markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON parse error: {e}")
        print(f"  Raw response: {text[:200]}...")
        return None


async def process_vacancy(
    filename: str,
    extractor_runner: InMemoryRunner,
    reviewer_runner: InMemoryRunner,
    dry_run: bool = False,
) -> bool:
    """Process a single vacancy through the two-agent pipeline."""
    print(f"\n{'='*60}")
    print(f"📄 Processing: {filename}")
    print(f"{'='*60}")

    # Step 1: Read vacancy
    content = skills_tools.read_vacancy(filename)
    if content.startswith("ERROR"):
        print(f"  ❌ {content}")
        return False

    # Step 2: Extract skills (Agent 1)
    print("  🔍 Agent 1 (Extractor): Analyzing vacancy...")
    extractor_response = await run_agent_once(
        extractor_runner,
        f"Extract skills from this vacancy:\n\n{content}",
        user_id="miner",
        session_id=f"extract_{filename}",
    )

    extracted = parse_json_response(extractor_response)
    if extracted is None or not isinstance(extracted, list):
        print(f"  ❌ Extractor returned invalid data, skipping")
        return False

    print(f"  ✅ Extracted {len(extracted)} skills: {[s.get('skill','?') for s in extracted]}")

    if not extracted:
        print("  ℹ️  No skills found, marking as processed")
        if not dry_run:
            skills_tools.mark_processed(filename)
        return True

    # Step 3: Review skills (Agent 2)
    print("  🧠 Agent 2 (Reviewer): Validating against graph...")
    graph_state = skills_tools.get_graph_state()
    synonyms = skills_tools.get_synonyms()

    reviewer_message = json.dumps({
        "extracted_skills": extracted,
        "graph_state": json.loads(graph_state),
        "synonyms": json.loads(synonyms),
    }, ensure_ascii=False)

    reviewer_response = await run_agent_once(
        reviewer_runner,
        f"Review these extracted skills:\n\n{reviewer_message}",
        user_id="miner",
        session_id=f"review_{filename}",
    )

    reviewed = parse_json_response(reviewer_response)
    if reviewed is None or not isinstance(reviewed, dict):
        print(f"  ❌ Reviewer returned invalid data, skipping")
        return False

    approved = reviewed.get("approved_skills", [])
    rejected = reviewed.get("rejected_skills", [])
    new_synonyms = reviewed.get("new_synonyms", [])

    print(f"  ✅ Approved: {len(approved)} | Rejected: {len(rejected)}")
    if rejected:
        print(f"     Rejected: {[r.get('skill','?') for r in rejected]}")

    if dry_run:
        print("  🏃 DRY RUN — would apply:")
        for skill in approved:
            print(f"     Link: '{skill['original']}' → [[{skill['canonical']}]]")
            print(f"     Skill note: {skill['canonical']} (parent: {skill.get('parent', [])})")
        return True

    # Step 4: Apply changes
    print("  📝 Applying changes...")

    # 4a. Insert wikilinks into vacancy
    replacements = [
        {"original": s["original"], "canonical": s["canonical"]}
        for s in approved
    ]
    link_result = skills_tools.insert_wikilinks(filename, replacements)
    print(f"     {link_result}")

    # 4b. Create/update skill notes
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

    # 4c. Add new synonyms
    for syn in new_synonyms:
        result = skills_tools.add_synonym(syn["abbreviation"], syn["canonical"])
        print(f"     {result}")

    # 4d. Mark as processed
    skills_tools.mark_processed(filename)
    print(f"  ✅ Done: {filename}")
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    # Parse CLI args
    limit = 0
    dry_run = False
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--limit" and i + 1 < len(sys.argv) - 1:
            limit = int(sys.argv[i + 2])
        elif arg.startswith("--limit="):
            limit = int(arg.split("=")[1])
        elif arg == "--dry-run":
            dry_run = True

    # Check API key
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY not set. Create a .env file or export it.")
        sys.exit(1)

    # Get unprocessed vacancies
    unprocessed = skills_tools.list_unprocessed_vacancies()
    total = len(unprocessed)
    print(f"\n📊 Total vacancies: {total}")

    if limit:
        unprocessed = unprocessed[:limit]
        print(f"   Processing limit: {limit}")

    if dry_run:
        print("   Mode: DRY RUN (no files will be modified)")

    if not unprocessed:
        print("   ✅ All vacancies already processed!")
        return

    # Create agents and runners
    extractor, reviewer = create_agents()
    extractor_runner = InMemoryRunner(agent=extractor, app_name="skills_miner_extractor")
    reviewer_runner = InMemoryRunner(agent=reviewer, app_name="skills_miner_reviewer")

    # Process vacancies
    success = 0
    failed = 0
    for i, filename in enumerate(unprocessed, 1):
        print(f"\n[{i}/{len(unprocessed)}]", end="")
        try:
            ok = await process_vacancy(filename, extractor_runner, reviewer_runner, dry_run)
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ❌ Error processing {filename}: {e}")
            failed += 1

        # Rate limiting
        if i < len(unprocessed):
            time.sleep(DELAY_BETWEEN_VACANCIES)

    # Summary
    print(f"\n{'='*60}")
    print(f"📊 Summary: {success} succeeded, {failed} failed out of {len(unprocessed)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
