"""
Unit tests for chrome_plugin/scoring.py.

The `llm` parameter is always injected — no real Gemini calls are made.
"""
from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_SAMPLE_PROFILE = {
    "candidate": {"full_name": "Aleksei Petrov", "location": "Lisbon, Portugal"},
    "narrative": {
        "headline": "Solutions Engineer with 8+ years closing B2B AI deals",
        "superpowers": ["Full presale cycle", "LLM integration"],
        "proof_points": [
            {"name": "Just AI", "hero_metric": "30+ enterprise AI projects"},
        ],
    },
    "target_roles": {"primary": ["Solutions Engineer", "Pre-Sales Engineer"]},
    "compensation": {"target_range": "€55K–80K"},
    "location": {
        "city": "Lisbon",
        "country": "Portugal",
        "languages": [
            {"language": "English", "level": "Professional"},
            {"language": "Russian", "level": "Native"},
        ],
    },
    "preferences": {
        "deal_breakers": ["On-site 4-5 days/week outside Lisbon Metro"],
    },
}

_SAMPLE_VACANCY = {
    "job_id": "1234",
    "title": "Senior Solutions Engineer",
    "company": "Acme AI",
    "location": "Remote",
    "employment": "Full-time",
    "description_text": (
        "We are looking for a Senior Solutions Engineer with 5+ years of B2B SaaS "
        "experience. Required: Python, LLM pipelines, pre-sales demos. Nice to have: "
        "AWS Bedrock. Fully remote, competitive salary."
    ),
}

_GOOD_JSON = json.dumps({
    "match_pct": 87,
    "summary": "Strong fit for Senior Solutions Engineer with LLM integration history",
    "skills": [
        {"name": "Python", "weight": 0.9, "evidence": "8 yrs at Just AI"},
        {"name": "Pre-sales", "weight": 0.95, "evidence": "Full presale cycle"},
    ],
    "gaps": [
        {"name": "AWS Bedrock", "severity": "soft", "mitigation": "Adjacent GCP + Gemini"},
    ],
})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_happy_path_returns_structured_result():
    from chrome_plugin.scoring import score_vacancy

    def fake_llm(prompt: str) -> str:
        return _GOOD_JSON

    result = score_vacancy(_SAMPLE_PROFILE, _SAMPLE_VACANCY, llm=fake_llm)

    assert result["match_pct"] == 87
    assert "summary" in result
    assert isinstance(result["skills"], list)
    assert isinstance(result["gaps"], list)
    assert result["skills"][0]["name"] == "Python"
    assert result["gaps"][0]["severity"] == "soft"


def test_malformed_json_triggers_retry_and_succeeds():
    """First call returns garbage → retry must deliver valid JSON."""
    from chrome_plugin.scoring import score_vacancy

    call_count = {"n": 0}

    def fake_llm(prompt: str) -> str:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "This is not JSON at all"
        return _GOOD_JSON

    result = score_vacancy(_SAMPLE_PROFILE, _SAMPLE_VACANCY, llm=fake_llm)
    assert call_count["n"] == 2
    assert result["match_pct"] == 87


def test_total_llm_failure_returns_error_dict():
    """Both calls return garbage → error dict with 'llm_error' key."""
    from chrome_plugin.scoring import score_vacancy

    def fake_llm(prompt: str) -> str:
        return "```I am a confused model```"

    result = score_vacancy(_SAMPLE_PROFILE, _SAMPLE_VACANCY, llm=fake_llm)
    assert result.get("error") == "llm_error"
    assert "raw" in result


def test_profile_and_vacancy_data_reach_the_prompt():
    """The fake LLM receives a prompt that contains key profile + vacancy snippets."""
    from chrome_plugin.scoring import score_vacancy

    seen_prompts = []

    def fake_llm(prompt: str) -> str:
        seen_prompts.append(prompt)
        return _GOOD_JSON

    score_vacancy(_SAMPLE_PROFILE, _SAMPLE_VACANCY, llm=fake_llm)

    assert seen_prompts, "fake_llm was never called"
    prompt = seen_prompts[0]
    # Profile data
    assert "Aleksei Petrov" in prompt
    assert "Solutions Engineer" in prompt
    assert "€55K–80K" in prompt
    # Vacancy data
    assert "Acme AI" in prompt
    assert "Senior Solutions Engineer" in prompt
    assert "LLM pipelines" in prompt


def test_score_vacancy_strips_markdown_fences():
    """Model wraps answer in ```json ... ``` — parser should still extract it."""
    from chrome_plugin.scoring import score_vacancy

    def fake_llm(prompt: str) -> str:
        return f"```json\n{_GOOD_JSON}\n```"

    result = score_vacancy(_SAMPLE_PROFILE, _SAMPLE_VACANCY, llm=fake_llm)
    assert result.get("match_pct") == 87
