<div align="center">

<br/>

```
██████╗  ██████╗ ███████╗███████╗██╗███████╗██████╗
██╔══██╗██╔═══██╗██╔════╝██╔════╝██║██╔════╝██╔══██╗
██║  ██║██║   ██║███████╗███████╗██║█████╗  ██████╔╝
██║  ██║██║   ██║╚════██║╚════██║██║██╔══╝  ██╔══██╗
██████╔╝╚██████╔╝███████║███████║██║███████╗██║  ██║
╚═════╝  ╚═════╝ ╚══════╝╚══════╝╚═╝╚══════╝╚═╝  ╚═╝
```

### Autonomous job search intelligence — built for ML/AI engineers.

*Apply smarter. Reach earlier. Improve every week.*

<br/>

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-package%20manager-7C3AED?style=for-the-badge)](https://docs.astral.sh/uv/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--5.4--mini-412991?style=for-the-badge&logo=openai&logoColor=white)](https://platform.openai.com/)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude%20Sonnet-D97757?style=for-the-badge)](https://anthropic.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)](LICENSE)

<br/>

[**What It Does**](#what-it-does) · [**Quick Start**](#quick-start) · [**Architecture**](#architecture) · [**Watchlist**](#watchlist-agent) · [**Roadmap**](#roadmap)

<br/>

> Dossier is not a job board wrapper or a resume template tool.
> It is a quality-first agentic system that finds, scores, and surfaces
> the jobs most worth your time — so you can apply to fewer roles, better.

</div>

---

## What It Does

Two complementary pipelines running in parallel:

<table>
<tr>
<td width="50%">

### 🔍 Job Discovery
Keyword search across **Indeed + LinkedIn** with 10 ML/AI search terms. Rule-based pre-filter eliminates ~60% of results before spending a single LLM token. The survivors are parallel-scored against your profile.

```
~550 raw jobs / run
  → ~60% filtered (free)
  → ~220 scored (LLM)
  → ~57 ranked results
  → ~31 high relevancy
  ⏱  ~2 min total
  💰  ~$0.04/run
```

</td>
<td width="50%">

### 🎯 Watchlist Agent
Company-specific search across **70 target companies** using LinkedIn `f_C=` company ID filters, Greenhouse free JSON API, and Lever free JSON API. Catches promoted listings that keyword search never sees.

```
70 target companies / run
  → Greenhouse: 4 companies (clean JSON)
  → LinkedIn f_C=: 66 companies
  → ~40 raw jobs
  → ~10 scored results
  → ~6 high relevancy
```

</td>
</tr>
</table>

---

## Features

- 🧠 **Profile-driven, not hardcoded** — swap `profile/profile.json` for any user, zero code changes
- ⚡ **Two-pass scoring** — rule-based gates (free) before LLM, ~60% of jobs never reach the API
- 🔀 **Parallel scoring** — 8-worker `ThreadPoolExecutor`, serial 10 min → 2 min
- 🏢 **Ground-truth company tiers** — 70 companies with verified MAANG / top product / AI startup tiers, no LLM guessing
- 📊 **Seniority-aware** — experience band computed at your planned switch date, penalises over/under-levelled roles
- 🚨 **Urgency tiers** — `URGENT / HIGH / NORMAL / LOW` from posting date (24h applications get 3× response rate)
- 🕵️ **Watchlist agent** — company-specific search via LinkedIn `f_C=`, Greenhouse API, Lever API
- 🔗 **LinkedIn ID resolver** — auto-resolves numeric company IDs from slugs, caches for future runs
- 📋 **Full audit trail** — every rejected job saved with score, reason, and description preview
- 🎯 **Parent company dedup** — `Amazon.com` + `Amazon Science` count as the same company in the diversity cap

---

## Quick Start

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), OpenAI API key, Anthropic API key

```bash
# 1. Clone
git clone https://github.com/shivangsingh26/dossier.git && cd dossier

# 2. Install
uv sync

# 3. Configure
cp .env.example .env
# Open .env → add OPENAI_API_KEY and ANTHROPIC_API_KEY

# 4. Build your profile
python scripts/run_persona_builder.py

# 5. Run
python scripts/run_job_discovery.py --hours 240
python scripts/run_watchlist.py --min-score 5
```

---

## Usage

```bash
# ── Job Discovery ────────────────────────────────────────────────────────────
# Last 10 days, minimum score 5/10 (default)
python scripts/run_job_discovery.py --hours 240

# Last 3 days, high relevancy only
python scripts/run_job_discovery.py --hours 72 --min-score 7

# ── Watchlist Agent ──────────────────────────────────────────────────────────
# All 70 target companies, default filters
python scripts/run_watchlist.py --min-score 5

# High relevancy only
python scripts/run_watchlist.py --min-score 7

# ── Utilities ────────────────────────────────────────────────────────────────
python scripts/run_persona_builder.py   # build / rebuild your profile
python tests/test_llm_client.py         # verify all LLM providers are responding
```

**Output files**

| File | Contents |
|---|---|
| `data/last_discovery_run.json` | All scored jobs from keyword discovery |
| `data/last_watchlist_run.json` | All scored jobs from watchlist agent |
| `data/rejected_jobs.json` | Every filtered job with reason + description preview |
| `data/linkedin_company_ids.json` | Cached LinkedIn slug → numeric ID map (auto-grows) |
| `data/artifacts/{job_id}/` | Per-job JD text + scorecard JSON |

---

## Architecture

### Scoring Pipeline

```
~550 raw jobs
    │
    ├─ is_hard_no()              ← service companies (TCS/Infosys/NTT DATA...)
    ├─ description < 100 chars   ← no content
    ├─ is_seniority_mismatch()   ← profile-driven: Senior/Staff/VP/Apprenticeship...
    └─ classify_job_function()   ← support_ops (SRE/DevOps/Infra) → skip
    │
    │  ~60% eliminated · zero LLM spend
    │
    ▼
ThreadPoolExecutor  ×8 workers
    │
    ├─ company_tier   ─── stated fact from target_companies.json
    │                      (maang=4pts · top_product=3pts · ai_startup=2pts)
    ├─ job_function   ─── stated fact from title keywords
    │                      (support_ops / pure_swe / ml_ai)
    └─ GPT-5.4-mini  ─── score 1–10 + reason + skill gaps
    │
    ├─ min_score gate (default 5/10)
    └─ parent-company diversity cap (max 5 per company)
    │
    └── Ranked terminal table · urgency · score · direct link
```

**Cost:** ~$0.03–0.06 per full discovery run (GPT-5.4-mini, ~100 jobs scored)

### Watchlist Agent

```
For each of 70 target companies:
    │
    ├─ ats_type == "greenhouse"  →  boards-api.greenhouse.io/v1/boards/{token}/jobs
    │                                 Stripe · Databricks · Airbnb · Coinbase
    │
    ├─ ats_type == "lever"       →  api.lever.co/v0/postings/{handle}?mode=json
    │
    └─ all others                →  LinkedIn f_C={company_id} filter
                                     resolve_linkedin_company_id(slug)
                                         ↳ multi-pattern HTML extraction
                                         ↳ cache: data/linkedin_company_ids.json
                                         ↳ fallback: /about/ page
    │
    └── ML title filter → same scoring pipeline as discovery
```

---

## Watchlist Agent

### Company Coverage — 70 Targets

<table>
<tr>
<td valign="top" width="25%">

**🏆 MAANG (6)**
Google · Microsoft
Amazon · Meta
Apple · Netflix

</td>
<td valign="top" width="25%">

**🌐 Top Global Product (19)**
Uber · Walmart GTC · Rippling
Stripe · Atlassian · Adobe
Salesforce · Intuit · NVIDIA
AMD · Qualcomm · PayPal
Databricks · Airbnb · LinkedIn
Coinbase · Wayfair · Target
Disney+ Hotstar · Zoho

</td>
<td valign="top" width="25%">

**🇮🇳 Top Indian Product (30)**
Flipkart · Zepto · Swiggy
Meesho · Razorpay · PhonePe
CRED · Dream11 · Groww · Juspay
Browserstack · Freshworks
Postman · InMobi · Ola
Zomato · Myntra · MakeMyTrip
Delhivery · upGrad · BharatPe
Tata 1mg · Physics Wallah
Urban Company · Rapido
Lenskart · Porter · ixigo
OYO · Navi · MPL

</td>
<td valign="top" width="25%">

**🤖 Top AI Startups (10)**
Sarvam AI · Krutrim AI
Uniphore · Yellow.ai
Observe.AI · Vue.ai
Sprinklr · Darwinbox
Auric AI Labs · Haptik

</td>
</tr>
</table>

### Fetch Strategy per Company

| Method | Companies | How |
|---|---|---|
| Greenhouse API | Stripe, Databricks, Airbnb, Coinbase | `boards-api.greenhouse.io` free JSON |
| Lever API | (Browserstack, when available) | `api.lever.co` free JSON |
| LinkedIn f_C= | All 66 others | Company-specific search, no keywords |

---

## Profile Configuration

`profile/profile.json` — generated by `run_persona_builder.py` or written manually

```json
{
  "identity": {
    "name": "Your Name",
    "total_experience_months": 20,
    "education": "B.Tech CS",
    "location": "Bengaluru"
  },
  "target": {
    "roles": ["MLE-1", "AI Engineer", "Data Scientist"],
    "locations": ["Bengaluru"],
    "min_salary_lpa": 25,
    "switch_timeline_months": 8,
    "search_terms": ["Machine Learning Engineer", "LLM Engineer", "NLP Engineer", "..."]
  },
  "skills": [
    { "skill": "PyTorch", "depth": "can_architect", "market_aliases": ["torch"] },
    { "skill": "LangChain", "depth": "can_build", "market_aliases": ["langchain"] }
  ],
  "known_gaps": ["Kubernetes", "Scala"]
}
```

---

## LLM Strategy

| Task | Model | Cost tier | Reason |
|---|---|---|---|
| Job scoring | `gpt-5.4-mini` | nano | Runs on every job — cost is the constraint |
| Company intel, referral ranking | `gpt-5.4-mini` | nano | Noisy scraped data needs reasoning |
| Persona interview, cold messages | `gpt-5` | quality | Conversational depth + tone matching |
| Cover letter generation | `claude-haiku-4-5` | claude | Good writing, cost-efficient |
| Resume bullet rewriting (LaTeX) | `claude-sonnet-4-6` | claude | LaTeX-aware, best precision |

All model names are constants in `config.py`. Changing any model is a one-line edit.
**Cost at scale:** $0.75/M input for GPT-5.4-mini. A full week of daily runs ≈ $0.30.

---

## Project Structure

```
dossier/
│
├── agents/
│   ├── job_discovery.py          # Pipeline: keyword search → pre-filter → parallel LLM score
│   ├── watchlist_agent.py        # Pipeline: company-specific search via Greenhouse/Lever/LinkedIn
│   └── persona_builder.py        # Terminal interview → profile.json
│
├── core/
│   ├── llm_client.py             # Single interface for OpenAI + Anthropic
│   ├── linkedin_scraper.py       # LinkedIn public guest API + company_id f_C= support
│   ├── file_vault.py             # Per-job artifact storage (jd.txt + scorecard.json)
│   └── logger.py                 # Centralised logging, module-level loggers
│
├── profile/
│   ├── profile.json              # Your persona — source of truth (gitignored)
│   ├── target_companies.json     # 70 companies: tier, LinkedIn slug, ATS type
│   └── exception_companies.json  # Companies we can't scrape + exact failure reason
│
├── scripts/
│   ├── run_job_discovery.py      # --hours  --min-score
│   └── run_watchlist.py          # --min-score  --location
│
├── data/
│   ├── last_discovery_run.json
│   ├── last_watchlist_run.json
│   ├── rejected_jobs.json
│   ├── linkedin_company_ids.json # Auto-growing slug → ID cache
│   └── artifacts/                # Per-job folders
│
├── tests/
│   └── test_llm_client.py        # Model health check for all 4 models
│
├── config.py                     # Singleton config + all model name constants
└── pyproject.toml                # uv-managed, hatchling build backend
```

---

## Product Vision

Dossier is built in tiers, each unlocking a new capability:

| Tier | What's unlocked | Status |
|---|---|---|
| **Dossier Lite** | Keyword job discovery — Indeed + LinkedIn, 10 search terms, LLM scoring | ✅ Built |
| **Dossier Pro** | + Watchlist agent — 70 target companies, Greenhouse/Lever/LinkedIn f_C= | ✅ Built |
| **Dossier Max** | + Company intel · Market intel · Referral finder · Cold outreach generator | 🔨 Building |

---

## Roadmap

**Phase A — Discovery** ✅ *complete*
- [x] Multi-source keyword discovery (Indeed + LinkedIn)
- [x] Two-pass scoring — rule-based pre-filter + parallel LLM
- [x] Company tier lookup from verified ground-truth file
- [x] Profile-driven seniority gating (experience band at switch time)
- [x] Parent company dedup — Amazon.com + Amazon Science share one diversity slot
- [x] Watchlist agent — company-specific search, 70 targets
- [x] LinkedIn company ID resolver with disk cache
- [x] Greenhouse + Lever free JSON API integration
- [x] exception_companies.json — permanent log of unscrapable companies

**Phase B — Enrichment** 🔨 *next*
- [ ] `extract_years_required()` — hard gate from JD text, no LLM cost
- [ ] `extract_degree_required()` — PhD/MS/BS from JD, passed as fact to LLM scorer
- [ ] Company intel agent — Crunchbase funding stage + Glassdoor rating per job ≥ 7
- [ ] SQLite dedup — skip rescoring jobs seen in previous runs (~40% cost reduction)
- [ ] Telegram alerts — URGENT jobs (score ≥ 7, posted < 24h) → instant push

**Phase C — Action** 📋 *planned*
- [ ] Market intel agent — monitor funding news, auto-add companies to watchlist
- [ ] Two-path logic: jobs found → watchlist · no jobs → cold outreach pipeline
- [ ] Gap analysis agent — skill delta between profile and top job requirements
- [ ] Referral finder — people at target companies worth reaching out to
- [ ] Cold outreach generator — personalised LinkedIn DM + cold email per contact
- [ ] Resume agent — LaTeX bullet rewriting via Claude Sonnet, per JD

**Phase D — Intelligence** 🔮 *future*
- [ ] LTR scorer — LightGBM trained on apply/response signal after 200+ labelled examples
- [ ] Two-tower ranking — BM25 candidate retrieval + LLM cross-encoder reranking

---

## Notes

- `profile/profile.json` is gitignored — personal data (salary, skills, name) stays local
- `profile/target_companies.json` is committed — just a list of company names and metadata
- `data/linkedin_company_ids.json` is gitignored — regenerates automatically on first run
- Phase A is intentionally synchronous plain Python — no async except the scoring executor
- The only hardcoded things: model names in `config.py`, service company keywords in `job_discovery.py`

---

<div align="center">

Built for engineers who want to work at places worth working at.

</div>
