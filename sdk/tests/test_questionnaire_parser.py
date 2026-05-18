"""Tests for persona_builder multi-user support."""
import os
import pytest
from pathlib import Path
from unittest.mock import patch
from dossier_sdk.agents.persona_builder import find_user_pdfs, parse_questionnaire_file, parse_questionnaire_file_from_string, INTERVIEW_QUESTIONS


def test_find_user_pdfs_detects_linkedin_by_name(tmp_path):
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 fake resume")
    (tmp_path / "linkedin_profile.pdf").write_bytes(b"%PDF-1.4 fake linkedin")
    resume, linkedin = find_user_pdfs(tmp_path)
    assert resume is not None
    assert linkedin is not None
    assert "linkedin" in linkedin.name.lower()
    assert "linkedin" not in resume.name.lower()


def test_find_user_pdfs_no_linkedin_returns_none(tmp_path):
    (tmp_path / "resume.pdf").write_bytes(b"%PDF-1.4 fake resume")
    resume, linkedin = find_user_pdfs(tmp_path)
    assert resume is not None
    assert linkedin is None


def test_find_user_pdfs_empty_dir_returns_none_none(tmp_path):
    resume, linkedin = find_user_pdfs(tmp_path)
    assert resume is None
    assert linkedin is None


SAMPLE_QUESTIONNAIRE = """\
DOSSIER — PROFILE QUESTIONNAIRE
================================
For: testuser

================================
== BASIC INFO ==
================================

Name: Test User
Current title / role (e.g. Software Engineer, Data Scientist): Data Scientist
Short title — 2-3 words to use in casual intros (e.g. Backend Engineer, AI Engineer): Data Scientist
Current company (write NONE if student or between jobs): Acme Corp
City / location (e.g. Bengaluru, India): Bengaluru, India
Education (e.g. B.Tech CS, IIIT SriCity): B.Tech CS, IIT Delhi
Total months of professional work experience (write 0 if fresher): 24
Current CTC in LPA (write 0 if student or not disclosed): 18
Notice period in months (write 0 if immediate joiner or student): 2
GitHub username (leave blank if none): testgithub

================================
== JOB TARGETS ==
================================

What job titles are you targeting? (comma separated)
TargetRoles: Data Scientist, MLE-1, AI Engineer

Minimum salary you will accept (in LPA):
MinSalary: 28

Preferred / expected salary (in LPA):
PrefSalary: 35

Locations you will work in (comma separated, e.g. Bengaluru, Remote):
Locations: Bengaluru, Remote

Types of companies or work you will NEVER join — your hard nos:
HardNos: service companies, bond agreements

By when do you want to switch? (e.g. 2027-01):
TargetBy: 2027-03

================================
== INTERVIEW ==
================================

[Q1] Technical Depth
Walk me through the most technically complex thing you built.
Tip: Be specific — tool names, what failed, what worked. Numbers help.

Answer:
Built a feature store using Feast and Redis for real-time ML inference.
Biggest challenge was cache invalidation — solved with TTL and versioned keys.

[Q2] Scale and Impact
What is the largest scale your code has run at?
Tip: Even small numbers are fine.

Answer:
Processed 2M daily events using Spark on EMR.

[Q3] Decision Making
Tell me about a technical decision you made and later had to defend or change.
Tip: No wrong answer.

Answer:
Chose Airflow over Prefect early on. Later moved to Prefect for better dynamic DAGs.

[Q4] Skill Assessment
List your top 5-7 technical skills.
Tip: skill: level

Answer:
Python: can_teach
SQL: can_architect
PyTorch: can_use
Spark: can_use
MLflow: can_use

[Q5] Known Gaps
What technical areas do you know you are weak in right now?
Tip: Honest gaps feed into cover letters.

Answer:
Weak in Kubernetes and distributed systems design. Want to learn at next role.

[Q6] Team Collaboration
Describe a recent project in terms of team structure.
Tip: Solo vs team signals.

Answer:
Team of 5. I owned the ML pipeline end to end. Handed off models to backend team.

[Q7] Why This Direction
Why are you targeting these specific roles and companies?
Tip: Your actual answer.

Answer:
Want to work on product ML that reaches real users, not just internal analytics.

[Q8] Good Week Vision
At your next company, what does a good week look like?
Tip: Work, team size, how you feel.

Answer:
Small team, ship a model improvement, get feedback from product. No politics.

[Q9] Hard Nos Detail
What would make you leave a role within 6 months?
Tip: Used to filter companies.

Answer:
No production ML, excessive process, bond agreements.

[Q10] Strongest Asset
What is the one thing you do better than most engineers at your level?
Tip: Opening line of cover letters.

Answer:
I can take a vague business problem and turn it into a concrete ML solution fast.

[Q11] Side Projects
What have you built outside your job in the last 12 months?
Tip: Self-directed learning is high signal.

Answer:
Built a tiny LLM eval harness. Wrote 3 blog posts on feature stores.

[Q12] Referral Pitch
If someone at Google asked 'why should I refer you?'
Tip: Write in your own voice.

Answer:
Strong ML fundamentals, shipped things to prod, fast learner who documents well.

[Q13] Your Voice
Write 2-3 sentences as you'd write in a LinkedIn message.
Tip: Natural voice.

Answer:
Hey, I'm Test — Data Scientist at Acme. I've spent two years building ML pipelines for e-commerce recommendations and I'm looking to move into a product company.

"""


def test_parse_basic_info():
    result = parse_questionnaire_file_from_string(SAMPLE_QUESTIONNAIRE)
    assert result["identity"]["name"] == "Test User"
    assert result["identity"]["months_experience"] == 24
    assert result["identity"]["current_ctc_lpa"] == 18
    assert result["identity"]["github_username"] == "testgithub"


def test_parse_targets():
    result = parse_questionnaire_file_from_string(SAMPLE_QUESTIONNAIRE)
    assert "Data Scientist" in result["target"]["roles"]
    assert result["target"]["min_salary_lpa"] == 28
    assert result["target"]["preferred_salary_lpa"] == 35
    assert "Bengaluru" in result["target"]["locations"]
    assert result["target"]["target_by"] == "2027-03"
    assert "service companies" in result["target"]["hard_nos"]


def test_parse_interview_answers():
    result = parse_questionnaire_file_from_string(SAMPLE_QUESTIONNAIRE)
    answers = result["interview_answers"]
    assert "technical_depth" in answers
    assert "feast" in answers["technical_depth"].lower()
    assert "scale_impact" in answers
    assert "2m" in answers["scale_impact"].lower()


def test_all_question_ids_present():
    result = parse_questionnaire_file_from_string(SAMPLE_QUESTIONNAIRE)
    expected_ids = {q["id"] for q in INTERVIEW_QUESTIONS}
    assert expected_ids == set(result["interview_answers"].keys())


def test_parse_questionnaire_file_reads_from_path(tmp_path):
    qfile = tmp_path / "questionnaire.md"
    qfile.write_text(SAMPLE_QUESTIONNAIRE, encoding="utf-8")
    result = parse_questionnaire_file(qfile)
    assert result["identity"]["name"] == "Test User"
