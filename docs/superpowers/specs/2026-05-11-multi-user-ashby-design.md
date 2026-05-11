# Phase 1 Design: Multi-user Pipeline + Ashby ATS Coverage

**Date:** 2026-05-11
**Status:** Approved — ready for implementation planning
**Goal:** Enable Dossier to run per-user (Shivang now, friends when questionnaires arrive) and close the biggest free-source coverage gap by adding Ashby ATS to the watchlist agent.

---

## Context

Dossier currently hardcodes all paths to a single user's profile and data directory. Three friends (Anushthan, Sambhav, Krishna) have profile directories with resumes and LinkedIn PDFs. Questionnaires sent — not yet returned. Multi-user infra must be ready before they come back.

On the discovery side: Naukri and Google Jobs are broken upstream in JobSpy. Wellfound is absent. The biggest free, high-ROI gap is Ashby ATS — ~10-15 Indian product companies currently scraped via fragile LinkedIn f_C= that have stable free Ashby JSON APIs.

---

## Section 1: Multi-user Pipeline

### Goal
`python run_dossier.py --user shivang` runs the full pipeline for Shivang.
`python scripts/run_persona_builder.py --user anushthan --answers profile/anushthan/questionnaire.md` builds Anushthan's profile when his questionnaire arrives.

### Config change

`Config.__new__` gains an optional `user: str = "shivang"` parameter.

- First call (at entry point): `Config(user=args.user)` — sets user, resolves all paths, locks singleton.
- All downstream agent calls: `Config()` — returns same instance, no change needed inside agents.

```python
def __new__(cls, user: str = "shivang"):
    if cls._instance is None:
        cls._instance = super().__new__(cls)
        cls._instance._load(user)
    return cls._instance
```

### Path isolation

| Attribute | Current | New |
|---|---|---|
| `profile_dir` | `profile/` | `profile/{user}/` |
| `profile_path` | `profile/profile.json` | `profile/{user}/profile.json` |
| `data_dir` | `data/` | `data/{user}/` |
| `db_path` | `data/dossier.db` | `data/{user}/dossier.db` |
| `artifacts_dir` | `data/artifacts/` | `data/{user}/artifacts/` |

Deprecate `PROFILE_PATH` env-var override — it was a workaround for the single-user limitation. Config will log a warning if it is set and ignore it, rather than hard-removing it (avoids silent breakage for anyone who has it in `.env`).

### Shared paths (not isolated — same for all users)

- `profile/target_companies.json` — same watchlist
- `profile/exception_companies.json` — same hard-nos
- `data/linkedin_company_ids.json` — company ID resolution cache

### Scripts that get `--user` flag

All entry points pass `Config(user=args.user)` as the first call before importing any agent.

| Script | Change |
|---|---|
| `run_dossier.py` | Add `--user`, default `shivang` |
| `scripts/run_job_discovery.py` | Add `--user`, default `shivang` |
| `scripts/run_watchlist.py` | Add `--user`, default `shivang` |
| `scripts/run_company_intel.py` | Add `--user`, default `shivang` |
| `scripts/run_gap_analysis.py` | Add `--user`, default `shivang` |
| `scripts/run_referral_finder.py` | Add `--user`, default `shivang` |
| `scripts/run_resume_agent.py` | Add `--user`, default `shivang` |
| `scripts/run_persona_builder.py` | Add `--user` + `--answers` (path to filled questionnaire) |
| `scripts/run_market_intel.py` | No change — market intel is global, not per-user |

### Persona builder multi-user flow

```
# Step 1 — already works (questionnaire template already scoped per user)
python scripts/export_questionnaire.py --user anushthan

# Step 2 — friend fills questionnaire.md, sends back, you drop it in place

# Step 3 — run persona builder with their answers (NEW --user + --answers flags)
python scripts/run_persona_builder.py --user anushthan --answers profile/anushthan/questionnaire.md
# → writes profile/anushthan/profile.json

# Step 4 — run full pipeline for that user
python run_dossier.py --user anushthan
# → reads profile/anushthan/profile.json
# → writes data/anushthan/dossier.db, data/anushthan/artifacts/
```

### Persona builder questionnaire file parsing (required new work)

`persona_builder.py` currently runs a live interactive terminal interview (`input()` per question). When `--answers` is provided, the script must parse the filled `questionnaire.md` instead of prompting.

**New function required in `agents/persona_builder.py`:**

```python
def parse_questionnaire_file(path: Path) -> tuple[dict, dict]:
    """
    Parse a filled questionnaire.md into basic_info dict + interview_answers dict.
    Returns (basic_info, interview_answers) — same shapes the interactive flow produces.
    """
```

The questionnaire format uses section markers the parser can split on:
- `== BASIC INFO ==` block → parse Name, title, company, CTC, etc.
- `== JOB TARGETS ==` block → parse TargetRoles, MinSalary, Locations, HardNos, TargetBy
- `[Q1]` through `[Q13]` blocks → extract text after `Answer:` up to next `[Q` marker

**`run()` in `persona_builder.py` gets optional `answers_path: Path | None = None`:**
- If `answers_path` is provided → call `parse_questionnaire_file()`, skip `conduct_interview()`
- If not provided → existing interactive flow unchanged (Shivang's own run_persona_builder still works)

**`run_persona_builder.py` script:**
```
python scripts/run_persona_builder.py                                            # interactive (Shivang)
python scripts/run_persona_builder.py --user anushthan --answers profile/anushthan/questionnaire.md
```

### Default user

Default `--user shivang` means all existing invocations (`python run_dossier.py`) continue working without change. No migration of existing data — `data/` and `profile/profile.json` stay untouched; the new layout starts fresh under `data/shivang/`.

**Decision:** Keep old `data/` and `profile/profile.json` as-is for now. Once confirmed working under `data/shivang/`, archive the old layout. Do not migrate automatically — migration is a manual step.

---

## Section 2: Ashby ATS Coverage

### Goal

Add Ashby as a 4th ATS strategy in `watchlist_agent.py`. Migrate Indian product companies from fragile LinkedIn f_C= scraping to stable Ashby JSON API where available.

### Ashby API

```
GET https://boards-api.ashbyhq.com/api/public/v0/job_posting/list
    ?organizationHostedJobsPageName={handle}
```

- Free, no auth, no rate-limit documented
- Returns `results[]` array
- Fields used: `title`, `locationName`, `publishedDate`, `jobPostingUrl`, `descriptionHtml`
- **Note:** Exact response schema must be verified against live API before coding — do not rely on training-data memory for field names.

### New function: `fetch_jobs_ashby(company_name, handle)`

Location: `watchlist_agent.py`, alongside `fetch_jobs_greenhouse()` and `fetch_jobs_lever()`.

Logic:
1. Call Ashby API for handle
2. Filter by `_ML_TITLE_KEYWORDS` (existing list — no change)
3. Filter by `_INDIA_LOCATION_KEYWORDS` (existing list — no change)
4. Normalize to same dict shape as Greenhouse/Lever output
5. Return list of job dicts — same shape, same downstream pipeline

No changes needed to scoring, dedup, file vault, or Telegram.

### `target_companies.json` schema addition

New `ats_type` value: `"ashby"`. Same structure as existing entries:

```json
{ "name": "PhonePe",  "ats_type": "ashby", "ats_token": "phonepe" }
{ "name": "Razorpay", "ats_type": "ashby", "ats_token": "razorpay" }
```

### Company list changes

**Migrate from LinkedIn f_C= → Ashby** (handles must be verified live before adding):
PhonePe, Razorpay, Meesho, Zepto, Slice, Setu, Jupiter, Porter, Jar, Khatabook

**Add to Greenhouse** (known public Greenhouse boards, not in watchlist yet — verify tokens live):
Groww, CRED, Navi

**Implementation rule:** Every handle and token must be verified by hitting the API before being committed to `target_companies.json`. A wrong handle fails silently (empty results) and creates a coverage gap — verify, don't assume.

### Dispatch in `watchlist_agent.py`

```python
if ats_type == "greenhouse" and ats_token:
    jobs = fetch_jobs_greenhouse(name, ats_token)
elif ats_type == "lever" and ats_token:
    jobs = fetch_jobs_lever(name, ats_token)
elif ats_type == "ashby" and ats_token:          # NEW
    jobs = fetch_jobs_ashby(name, ats_token)      # NEW
else:
    jobs = fetch_jobs_linkedin(name, company_id, location)
```

---

## What is NOT in this phase

- Wellfound / AngelList source (market_intel_agent already surfaces funded startups — lower priority)
- Job tracking / application status table (Phase 2)
- Naukri / Google Jobs (broken upstream in JobSpy — deferred)
- UI, web dashboard, any frontend

---

## Success criteria

1. `python run_dossier.py --user shivang` runs identically to current `python run_dossier.py`
2. `python run_dossier.py --user anushthan` runs against `profile/anushthan/profile.json` and writes to `data/anushthan/`
3. `python run_persona_builder.py --user anushthan --answers profile/anushthan/questionnaire.md` builds `profile/anushthan/profile.json`
4. Ashby companies return structured job data matching the existing scorecard schema
5. No regressions in existing scoring, dedup, company intel, gap analysis stages
