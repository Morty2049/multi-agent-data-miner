"""
chrome_plugin/scoring.py — Vacancy ↔ candidate profile match scoring.

Calls Gemini-Flash by default (lazy import so tests without GOOGLE_API_KEY
never fail at import time).  The `llm` seam lets tests inject a fake callable
that returns a canned JSON string instead of hitting the real API.

Public API
----------
score_vacancy(profile, vacancy, *, llm=None) -> dict
    Returns:
        {
            "match_pct": 87,
            "summary": "...",
            "skills": [{"name": ..., "weight": ..., "evidence": ...}, ...],
            "gaps":   [{"name": ..., "severity": "soft"|"hard", "mitigation": ...}, ...]
        }
    On error:
        {"error": "llm_error", "raw": "<truncated model output>"}
"""
from __future__ import annotations

import json
import os
from typing import Callable


# ---------------------------------------------------------------------------
# Prompt template (compact — stays under 2000 tokens of input)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a technical recruiter evaluating a candidate against a job vacancy.
Return ONLY a JSON object — no markdown, no prose, no code fences.

JSON schema:
{
  "match_pct": <integer 0-100>,
  "summary": "<1-2 sentence plain English summary>",
  "skills": [
    {"name": "<skill>", "weight": <0.0-1.0>, "evidence": "<one line from profile>"}
  ],
  "gaps": [
    {"name": "<gap>", "severity": "soft"|"hard", "mitigation": "<one-line plan>"}
  ]
}

Rules:
- match_pct: overall fit percentage considering skills, seniority, role archetype, location/remote, language, compensation.
- skills: list required/preferred skills the candidate DOES have, with weight = relevance to this specific role.
- gaps: skills/requirements the candidate lacks or has only adjacent experience in.
- severity: "hard" = likely blocker, "soft" = nice-to-have or mitigatable.
- Keep evidence and mitigation concise (max 15 words each).
- Output ONLY the JSON object. Any prose outside the JSON will break the parser.
"""

_MAX_DESCRIPTION_CHARS = 3000

_USER_TEMPLATE = """\
## Candidate Profile

Name: {full_name}
Headline: {headline}
Location: {location}
Languages: {languages}
Target roles: {target_roles}
Compensation target: {target_range}

Superpowers:
{superpowers}

Key proof points:
{proof_points}
{skills_section}
Deal-breakers (if vacancy triggers these → lower match_pct significantly):
{deal_breakers}

## Vacancy

Title: {title}
Company: {company}
Location: {vac_location}
Employment: {employment}

Description (truncated to {max_desc_chars} chars):
{description}
"""


def _build_prompt(profile: dict, vacancy: dict) -> str:
    """Compact the profile into the fields that matter for scoring."""
    cand = profile.get("candidate") or {}
    narrative = profile.get("narrative") or {}
    compensation = profile.get("compensation") or {}
    location = profile.get("location") or {}
    prefs = profile.get("preferences") or {}
    target_roles = profile.get("target_roles") or {}

    full_name = cand.get("full_name") or ""
    headline = narrative.get("headline") or ""

    loc_str = (
        cand.get("location")
        or f"{location.get('city', '')} / {location.get('country', '')}".strip(" /")
        or "Unknown"
    )

    langs = location.get("languages") or []
    lang_str = ", ".join(
        f"{l['language']} ({l['level']})" for l in langs if isinstance(l, dict)
    ) or "Not specified"

    primary_roles = target_roles.get("primary") or []
    role_str = ", ".join(primary_roles) or "Not specified"

    target_range = compensation.get("target_range") or "Not specified"

    superpowers = narrative.get("superpowers") or []
    sp_str = "\n".join(f"  - {s}" for s in superpowers) if superpowers else "  - (none listed)"

    proof_points = narrative.get("proof_points") or []
    pp_str = "\n".join(
        f"  - {p['name']}: {p.get('hero_metric','')}"
        for p in proof_points
        if isinstance(p, dict)
    ) or "  - (none listed)"

    deal_breakers = prefs.get("deal_breakers") or []
    db_str = "\n".join(f"  - {d}" for d in deal_breakers) or "  - (none listed)"

    # Build skills section from profile data, not hardcoded
    skills_lines: list[str] = []
    for s in superpowers:
        if isinstance(s, str):
            skills_lines.append(f"  - {s}")
    for p in proof_points:
        if isinstance(p, dict) and p.get("name"):
            metric = p.get("hero_metric", "")
            line = f"  - {p['name']}: {metric}" if metric else f"  - {p['name']}"
            skills_lines.append(line)
    if skills_lines:
        skills_section = "Skills implied by narrative:\n" + "\n".join(skills_lines) + "\n\n"
    else:
        skills_section = ""

    # Vacancy fields
    title = vacancy.get("title") or vacancy.get("job_title") or "(unknown role)"
    company = vacancy.get("company") or "(unknown company)"
    vac_location = vacancy.get("location") or "Not specified"
    employment = vacancy.get("employment") or "Not specified"
    description = (vacancy.get("description_text") or vacancy.get("description") or "")[:_MAX_DESCRIPTION_CHARS]

    return _USER_TEMPLATE.format(
        full_name=full_name,
        headline=headline,
        location=loc_str,
        languages=lang_str,
        target_roles=role_str,
        target_range=target_range,
        superpowers=sp_str,
        proof_points=pp_str,
        skills_section=skills_section,
        deal_breakers=db_str,
        title=title,
        company=company,
        vac_location=vac_location,
        employment=employment,
        description=description,
        max_desc_chars=_MAX_DESCRIPTION_CHARS,
    )


def _parse_json_response(text: str) -> dict | None:
    """Try to extract a JSON object from the model's raw response."""
    text = text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _default_llm(prompt_text: str) -> str:
    """Call Gemini-Flash via google.genai. Lazy import so tests never need the SDK."""
    # Import inside the function to avoid import-time dependency on GOOGLE_API_KEY
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt_text,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.1,
        ),
    )
    return response.text or ""


def score_vacancy(
    profile: dict,
    vacancy: dict,
    *,
    llm: Callable[[str], str] | None = None,
) -> dict:
    """Score a vacancy against the candidate profile.

    Parameters
    ----------
    profile:
        Candidate profile dict (same shape as profile.yml).
    vacancy:
        Vacancy dict with at minimum 'title', 'description_text'/'description',
        'company', 'location', 'employment'.
    llm:
        Optional callable(prompt_str) -> response_str.  Defaults to Gemini-Flash.
        Tests pass a fake here so no real API calls are made during testing.

    Returns
    -------
    dict with keys: match_pct, summary, skills, gaps
    or {"error": "llm_error", "raw": ...} on unrecoverable failure.
    """
    if llm is None:
        llm = _default_llm

    user_prompt = _build_prompt(profile, vacancy)

    # First attempt — pass only the user turn; _default_llm supplies
    # _SYSTEM_PROMPT via system_instruction in GenerateContentConfig.
    raw = llm(user_prompt)
    result = _parse_json_response(raw)

    if result is None:
        # Retry with an explicit reminder
        retry_prompt = (
            user_prompt
            + "\n\nIMPORTANT: Respond ONLY with valid JSON. No markdown, no prose."
        )
        raw = llm(retry_prompt)
        result = _parse_json_response(raw)

    if result is None:
        return {"error": "llm_error", "raw": raw[:500] if raw else ""}

    return result
