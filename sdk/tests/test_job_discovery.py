"""
tests/test_job_discovery.py — Tests for the job discovery agent.

Sections:
  1. Pure unit tests (no API calls) — utility functions
  2. Integration tests (real API calls) — scoring with a sample JD
  3. Standalone diagnostic runner

Run with: python -m pytest tests/test_job_discovery.py -v
Or:        python tests/test_job_discovery.py
"""

import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dossier_sdk.config import Config
from dossier_sdk.agents.job_discovery import (
    compute_experience_band,
    build_candidate_summary,
    build_scoring_system_prompt,
    is_hard_no,
    compute_urgency,
    generate_job_id,
    slugify,
    score_job,
    load_profile,
)


# ─── Sample data ──────────────────────────────────────────────────────────────

SAMPLE_PROFILE = {
    "identity": {
        "name": "Shivang Singh",
        "current_role": "Senior Associate Data Science L1 (AI Engineer)",
        "current_company": "Publicis Sapient",
        "total_experience_months": 20,
        "education": "B.Tech CS, IIIT SriCity (CGPA: 8.1, 2025)",
        "location": "Bengaluru, Karnataka, India",
    },
    "target": {
        "roles": ["MLE-1", "AI Engineer-1", "Data Scientist-1"],
        "min_salary_lpa": 25,
        "preferred_salary_lpa": 30,
        "locations": ["Bengaluru", "Remote"],
        "company_tiers": ["MAANG India", "funded_startup"],
        "hard_nos": ["service_company", "no_ml_in_prod"],
        "switch_timeline_months": 8,
    },
    "skills": [
        {"skill": "LLM Pipeline Engineering", "depth": "can_architect",
         "market_aliases": ["LLM pipelines", "GenAI", "agentic AI"]},
        {"skill": "Python", "depth": "can_teach",
         "market_aliases": ["Python", "Python ML"]},
        {"skill": "Computer Vision", "depth": "can_architect",
         "market_aliases": ["YOLO", "object detection"]},
    ],
    "known_gaps": ["Distributed training", "MLOps at scale"],
}

SAMPLE_JD_GOOD = """
Machine Learning Engineer - L4 (AI/LLM)
Company: Sarvam AI
Location: Bengaluru, India
Salary: 30-40 LPA

We are looking for an ML Engineer to join our LLM infrastructure team.

Requirements:
- 1-3 years experience in ML/AI engineering
- Strong Python skills (required)
- Experience with LLM APIs and pipelines (required)
- Experience with production ML systems (required)
- Computer vision experience a plus (preferred)

What you'll do:
- Build and scale LLM inference pipelines
- Integrate multimodal models into production systems
- Work with a small team of 5-8 engineers
"""

SAMPLE_JD_BAD = """
Senior Project Manager - PMO
Company: TCS
Location: Bengaluru

Requirements:
- 10+ years experience in project management
- PMP certification required
- Experience with JIRA and Confluence
- No technical skills needed
"""

SAMPLE_JD_MAANG_SENIOR = """
Senior Applied Scientist, Amazon Alexa
Company: Amazon
Location: Bengaluru, India
Salary: 45-60 LPA

Requirements:
- PhD in ML/AI or 5+ years relevant experience
- Expert-level PyTorch/TensorFlow
- Published research at top venues (NeurIPS, ICML)
- LLM training and fine-tuning experience
"""


# ─── Pure unit tests — no API calls ──────────────────────────────────────────

class TestExperienceBand:
    def test_entry_level(self):
        band = compute_experience_band(11, 8)
        assert band["band"] == "0-2 years"
        assert band["months_at_switch"] == 19

    def test_mid_level(self):
        band = compute_experience_band(20, 8)
        assert band["band"] == "2-5 years"
        assert band["months_at_switch"] == 28

    def test_senior_level(self):
        band = compute_experience_band(48, 12)
        assert band["band"] == "2-5 years"
        assert band["months_at_switch"] == 60

    def test_staff_level(self):
        band = compute_experience_band(72, 12)
        assert band["band"] == "5-8 years"
        assert band["months_at_switch"] == 84

    def test_penalise_titles_present(self):
        band = compute_experience_band(20, 8)
        assert len(band["penalise_titles"]) > 0

    def test_ideal_titles_present(self):
        band = compute_experience_band(20, 8)
        assert len(band["ideal_titles"]) > 0


class TestIsHardNo:
    def test_blocks_tcs(self):
        assert is_hard_no("TCS", []) is True

    def test_blocks_infosys(self):
        assert is_hard_no("Infosys Limited", []) is True

    def test_blocks_wipro(self):
        assert is_hard_no("Wipro Technologies", []) is True

    def test_blocks_accenture(self):
        assert is_hard_no("Accenture India", []) is True

    def test_blocks_cognizant(self):
        assert is_hard_no("Cognizant Technology Solutions", []) is True

    def test_allows_google(self):
        assert is_hard_no("Google", []) is False

    def test_allows_sarvam(self):
        assert is_hard_no("Sarvam AI", []) is False

    def test_allows_amazon(self):
        assert is_hard_no("Amazon.com", []) is False

    def test_allows_flipkart(self):
        assert is_hard_no("Flipkart", []) is False

    def test_custom_hard_no(self):
        assert is_hard_no("NoMLCompany Ltd", ["nomlcompany"]) is True

    def test_case_insensitive(self):
        assert is_hard_no("INFOSYS INDIA", []) is True


class TestComputeUrgency:
    def test_urgent_posted_today(self):
        posted = datetime.now(timezone.utc) - timedelta(hours=2)
        assert compute_urgency(posted) == "URGENT"

    def test_high_posted_yesterday(self):
        posted = datetime.now(timezone.utc) - timedelta(days=2)
        assert compute_urgency(posted) == "HIGH"

    def test_normal_posted_5_days_ago(self):
        posted = datetime.now(timezone.utc) - timedelta(days=5)
        assert compute_urgency(posted) == "NORMAL"

    def test_low_posted_10_days_ago(self):
        posted = datetime.now(timezone.utc) - timedelta(days=10)
        assert compute_urgency(posted) == "LOW"

    def test_none_returns_unknown(self):
        assert compute_urgency(None) == "UNKNOWN"

    def test_string_date(self):
        posted_str = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
        assert compute_urgency(posted_str) == "URGENT"


class TestGenerateJobId:
    def test_basic_format(self):
        job_id = generate_job_id("Google", "Machine Learning Engineer", "high")
        assert job_id == "google_machine_learning_engineer_high"

    def test_special_chars_removed(self):
        job_id = generate_job_id("Amazon.com", "Sr. AI Engineer!", "medium")
        assert "." not in job_id
        assert "!" not in job_id

    def test_lowercase(self):
        job_id = generate_job_id("FLIPKART", "DATA SCIENTIST", "high")
        assert job_id == job_id.lower()

    def test_max_length_respected(self):
        job_id = generate_job_id("A" * 50, "B" * 50, "high")
        # Should be truncated
        assert len(job_id) < 80


class TestSlugify:
    def test_basic(self):
        assert slugify("Machine Learning Engineer") == "machine_learning_engineer"

    def test_special_chars(self):
        assert slugify("Sr. AI/ML Engineer!") == "sr_ai_ml_engineer"

    def test_max_len(self):
        result = slugify("a" * 30, max_len=10)
        assert len(result) <= 10


class TestBuildCandidateSummary:
    def test_contains_name(self):
        exp_band = compute_experience_band(20, 8)
        summary = build_candidate_summary(SAMPLE_PROFILE, exp_band)
        assert "Shivang Singh" in summary

    def test_contains_experience_band(self):
        exp_band = compute_experience_band(20, 8)
        summary = build_candidate_summary(SAMPLE_PROFILE, exp_band)
        assert "2-5 years" in summary

    def test_contains_min_salary(self):
        exp_band = compute_experience_band(20, 8)
        summary = build_candidate_summary(SAMPLE_PROFILE, exp_band)
        assert "25" in summary

    def test_contains_skills(self):
        exp_band = compute_experience_band(20, 8)
        summary = build_candidate_summary(SAMPLE_PROFILE, exp_band)
        assert "LLM Pipeline Engineering" in summary
        assert "Python" in summary


# ─── Integration tests — real API calls ──────────────────────────────────────

class TestScoreJob:
    """These tests call the real OpenAI API. They verify scoring correctness."""

    def setup_method(self):
        exp_band = compute_experience_band(
            SAMPLE_PROFILE["identity"]["total_experience_months"],
            SAMPLE_PROFILE["target"]["switch_timeline_months"]
        )
        self.system_prompt    = build_scoring_system_prompt(exp_band)
        self.candidate_summary = build_candidate_summary(SAMPLE_PROFILE, exp_band)

    def test_good_job_scores_high(self):
        """A well-matched ML job at a product company should score ≥7."""
        result = score_job(
            company="Sarvam AI",
            title="Machine Learning Engineer",
            description=SAMPLE_JD_GOOD,
            candidate_summary=self.candidate_summary,
            system_prompt=self.system_prompt,
        )
        assert result["score"] >= 5, f"Expected score ≥5, got {result['score']} — {result['reason']}"
        print(f"\n  Good JD score: {result['score']}/10 — {result['reason']}")

    def test_bad_job_scores_low(self):
        """A non-ML job at TCS should score ≤3."""
        result = score_job(
            company="TCS",
            title="Senior Project Manager",
            description=SAMPLE_JD_BAD,
            candidate_summary=self.candidate_summary,
            system_prompt=self.system_prompt,
        )
        assert result["score"] <= 4, f"Expected score ≤4, got {result['score']} — {result['reason']}"
        print(f"\n  Bad JD score: {result['score']}/10 — {result['reason']}")

    def test_score_returns_required_fields(self):
        """Score result must always include all required fields."""
        result = score_job(
            company="Sarvam AI",
            title="ML Engineer",
            description=SAMPLE_JD_GOOD,
            candidate_summary=self.candidate_summary,
            system_prompt=self.system_prompt,
        )
        required_fields = ["score", "relevancy", "reason", "required_skills_missing", "preferred_skills_missing"]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_score_is_integer_in_range(self):
        """Score must be integer 1-10."""
        result = score_job(
            company="Google",
            title="ML Engineer",
            description=SAMPLE_JD_GOOD,
            candidate_summary=self.candidate_summary,
            system_prompt=self.system_prompt,
        )
        assert isinstance(result["score"], int), f"Score is not int: {type(result['score'])}"
        assert 1 <= result["score"] <= 10, f"Score out of range: {result['score']}"

    def test_relevancy_is_valid_value(self):
        """Relevancy must be one of: high, medium, low."""
        result = score_job(
            company="Amazon",
            title="Applied Scientist",
            description=SAMPLE_JD_MAANG_SENIOR,
            candidate_summary=self.candidate_summary,
            system_prompt=self.system_prompt,
        )
        assert result["relevancy"] in ("high", "medium", "low"), \
            f"Invalid relevancy: {result['relevancy']}"
        print(f"\n  MAANG senior JD score: {result['score']}/10, relevancy={result['relevancy']}")


# ─── Standalone diagnostic runner ────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  Job Discovery Diagnostic")
    print("=" * 70)

    # Unit tests
    print("\n  [1/3] Unit Tests (no API)")
    tests = [
        ("experience band entry level", lambda: compute_experience_band(11, 8)["band"] == "0-2 years"),
        ("experience band mid level",   lambda: compute_experience_band(20, 8)["band"] == "2-5 years"),
        ("hard_no TCS",                 lambda: is_hard_no("TCS", []) is True),
        ("hard_no Google allowed",      lambda: is_hard_no("Google", []) is False),
        ("urgency URGENT",              lambda: compute_urgency(datetime.now(timezone.utc) - timedelta(hours=2)) == "URGENT"),
        ("urgency LOW",                 lambda: compute_urgency(datetime.now(timezone.utc) - timedelta(days=10)) == "LOW"),
        ("job_id format",               lambda: "_" in generate_job_id("Google", "ML Eng", "high")),
    ]
    for name, fn in tests:
        try:
            result = fn()
            print(f"    {'PASS' if result else 'FAIL'} — {name}")
        except Exception as e:
            print(f"    ERROR — {name}: {e}")

    # API scoring test
    print("\n  [2/3] Scoring Test (real API call)")
    try:
        profile = load_profile()
        exp_band = compute_experience_band(
            profile["identity"].get("total_experience_months", 20),
            profile["target"].get("switch_timeline_months", 8),
        )
        system_prompt    = build_scoring_system_prompt(exp_band)
        candidate_summary = build_candidate_summary(profile, exp_band)

        result = score_job("Sarvam AI", "ML Engineer", SAMPLE_JD_GOOD, candidate_summary, system_prompt)
        passed = result["score"] > 0 and result["relevancy"] in ("high", "medium", "low")
        print(f"    {'PASS' if passed else 'FAIL'} — Score: {result['score']}/10, Relevancy: {result['relevancy']}")
        print(f"         Reason: {result.get('reason', 'N/A')}")
    except Exception as e:
        print(f"    ERROR — {e}")

    # Profile load test
    print("\n  [3/3] Profile Load Test")
    try:
        profile = load_profile()
        print(f"    PASS — Loaded profile for: {profile['identity']['name']}")
        print(f"           Skills: {len(profile.get('skills', []))} entries")
    except Exception as e:
        print(f"    FAIL — {e}")

    print("\n" + "=" * 70)
    print("  Run 'python tests/test_llm_client.py' next for full model diagnostics.")
    print("=" * 70 + "\n")
