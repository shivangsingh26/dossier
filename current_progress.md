# Dossier — Current Progress

Last updated: 2026-05-17

---

## What is Dossier

Autonomous agentic job search system. Finds relevant jobs based on a deep user persona, scores them, researches companies, finds referral contacts, tailors resumes. Three active users: **shivang** (ml_ai), **krishna** (ml_ai), **anushthan** (sde).

---

## Implemented (as of 2026-05-17)

### Multi-user pipeline
- `Config(user=...)` scopes all paths to `data/{user}/` and `profile/{user}/`
- All `run_*.py` scripts and `run_dossier.py` accept `--user` flag
- `run_dossier.py` data dirs (`data_dir`, `artifacts_dir`) now use Config singleton, no hardcoded paths
- Folder: `profile/Anushthan/` → `profile/anushthan/` (lowercase, consistent)

### Persona builder (agents/persona_builder.py)
- **Schema v2**: new fields `full_time_months`, `intern_months` (replaced broken `total_experience_months`), `certifications`, `publications`, `key_projects`, `preferred_work_style`, `open_to_relocation`, `relocation_cities`
- **Clash resolution rules** added to synthesis prompt (resume vs LinkedIn priority table)
- **Identity forwarding fix**: `short_title`, `current_ctc_lpa`, `notice_period_months` from questionnaire now forwarded to LLM (previously only `github_username` was passed)
- **short_title fix**: LLM now uses questionnaire value verbatim (was inferring from LinkedIn headline)
- **`safe_int` fix**: handles float strings like "37.4" → 37
- `tone_ref`/`voice_ref` set deterministically post-synthesis (file-exists check), not hardcoded to `profile/me/`
- Q7 interview question made generic (was "Why AI Engineering" — ML-specific)
- `max_tokens` bumped 4096 → 6000
- `export_questionnaire.py`: WorkStyle + Relocation fields added, experience split into `Full-time months` / `Internship months`
- All three profiles regenerated with new schema

### Job scoring (agents/job_discovery.py + watchlist_agent.py)
- **Role-domain aware scoring**: `build_scoring_system_prompt` now generic — uses `target_roles` + `role_domain` from profile (was hardcoded "AI/ML Engineer")
- **Scoring criterion 2** now: "does job match candidate's domain?" (not hardcoded ML criteria)
- **`classify_job_function`**: rich keyword lists for ml_ai/sde/data domains; SDE users: ML/DS titles → `off_domain` (0 pts), backend titles → target
- **`function_labels`** in `score_job`: domain-specific context sent to LLM
- **Experience field fix**: reads `full_time_months` (>0) else `intern_months`; `switch_months` computed from `target_by` date
- **Default search terms**: removed hardcoded ML fallback — now uses `target.roles`
- **Description scoring window**: 2500 → 4000 chars
- `build_candidate_summary`: fixed `total_experience_months` field name

### Watchlist agent (agents/watchlist_agent.py)
- **Domain-filtered companies**: `is_relevant_for_domain()` filters target companies by user's `role_domain` using `target_domains` field
- **Profile-driven title filter**: `is_target_domain_title()` uses `watchlist_title_keywords` from profile (replaced hardcoded `_ML_TITLE_KEYWORDS`)
- **Hardcoded "ML/AI jobs" log messages** → "matching jobs"
- Greenhouse + Lever + LinkedIn fetchers all accept `watchlist_keywords` param

### Target companies (profile/target_companies.json)
- Added `target_domains` field to all 71 existing companies
  - `"all"`: 64 companies (MAANG, Flipkart, Zepto, Swiggy, Rippling, etc.) — shown to every user
  - `"ml_ai"`: 8 companies (Sarvam AI, Krutrim AI, Uniphore, Yellow.ai, Observe.AI, Vue.ai, Auric AI Labs, Haptik) — ML users only
- Added 8 new SDE-focused companies (`"sde"` domain): Cisco Systems India, NetApp India, Nutanix India, Cohesity India, Rubrik India, Palo Alto Networks India, ServiceNow India, Datadog India

### Dashboard (dashboard.py)
- **Streamlit job tracker portal** with per-user password auth
- Login page → session locked to authenticated user (no user switcher)
- KPI cards: Total Found, Score ≥ 8, Interested, Applied, To Review
- Review progress bar
- Search box + tab navigation (All / Interested / Applied / Not Reviewed / Skipped / Rejected)
- Inline-editable job table — status dropdown + notes — auto-saves to `job_status` table in `dossier.db`
- Job detail panel: score reason, skill gap tags, quick-status buttons, notes textarea
- Full JD display (no truncation)
- `scripts/set_password.py`: set/update SHA-256 hashed passwords → `profile/auth.json`

---

## Known schema change (breaking for old profiles)

Shivang's `profile/shivang/profile.json` was on old schema (`total_experience_months`, `switch_timeline_months`). **Regenerated** with new schema during this session. All three profiles now symmetric.

---

## Active users + profiles

| User | role_domain | full_time_months | intern_months | certifications | publications | key_projects |
|---|---|---|---|---|---|---|
| shivang | ml_ai | 11 | 9 | 5 (Google Cloud x3, Stanford, Kaggle) | 0 | 5 |
| krishna | ml_ai | 16 | 18 | 0 | 2 (IEEE + Springer) | 4 |
| anushthan | sde | 11 | 6 | 5 | 0 | 5 |

---

## Last pipeline run (anushthan, 2026-05-16, --mode quick --hours 24)

**Discovery**: 1 job above score 5 (Amazon "Systems Development Engineer, FireTV" — score 8/10)
**Watchlist**: 0 jobs above score 5 (54 fetched, all pre-filtered — 27 seniority, 9 exp too high, 12 already seen, 4 short, 2 PhD)

**Root causes diagnosed and fixed:**
- Target companies list was ML-biased — now domain-filtered
- Watchlist title filter was ML hardcoded — now uses profile's `watchlist_title_keywords`
- 8 SDE-specific companies added to watchlist

**Pending**: re-run Anushthan with `--hours 168` to get 1 week of data and see full SDE job landscape with fixes applied.

---

## Next steps

1. Run `python run_dossier.py --user anushthan --mode quick --hours 168` — verify SDE-correct jobs, no DS/ML in results
2. Run `python run_dossier.py --user shivang --mode full` — run full pipeline with all fixes applied
3. Run `python run_dossier.py --user krishna --mode quick` — baseline run for Krishna
4. Add sambhav to the system (questionnaire + persona build)
5. Google Sheets tracker (STEP 03) — for persistent shareable job list
6. Resume agent test — generate tailored resume for a specific job
