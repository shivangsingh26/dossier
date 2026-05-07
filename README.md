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

**Autonomous job search intelligence for ML/AI engineers.**

*Apply smarter. Reach earlier. Improve every week.*

<br/>

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-package%20manager-7C3AED?style=flat-square&logo=astral&logoColor=white)](https://docs.astral.sh/uv/)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--5.4--mini-412991?style=flat-square&logo=openai&logoColor=white)](https://platform.openai.com/)
[![Anthropic](https://img.shields.io/badge/Anthropic-Claude%20Sonnet-D97757?style=flat-square)](https://anthropic.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-22C55E?style=flat-square)](LICENSE)
[![Phase](https://img.shields.io/badge/Phase-B%20%E2%80%94%20In%20Progress-f59e0b?style=flat-square)]()

<br/>

[What it does](#what-it-does) · [Quick start](#quick-start) · [Pipeline](#pipeline) · [Architecture](#architecture) · [Roadmap](#roadmap)

<br/>

> **Dossier is not a job board wrapper or a resume template tool.**
> It is a quality-first agentic pipeline that finds, scores, researches, and surfaces
> the roles most worth your time — so you can apply to fewer roles, better, earlier.

</div>

---

## What it does

Most job search tools solve the wrong problem. They give you *more* — more listings, more filters, more tabs open. Dossier gives you *signal*: the right 10 roles from the right 70 companies, with context on each one before you click apply.

<br/>

<table>
<tr>
<td width="50%" valign="top">

### Discovery
Keyword search across **Indeed + LinkedIn** using 10 ML/AI terms from your profile. A rule-based pre-filter eliminates ~60% of results before a single LLM token is spent. The survivors are parallel-scored in ~2 minutes.

```
~550 raw  →  ~220 scored  →  ~57 ranked
                              ┗ ~31 high relevancy
⏱  ~2 min    💰  ~$0.04/run
```

</td>
<td width="50%" valign="top">

### Watchlist
Company-specific search across **70 hand-picked companies** using LinkedIn `f_C=` filters, Greenhouse, and Lever free JSON APIs. Finds promoted and internal listings that keyword search never surfaces.

```
70 companies  →  ~40 raw  →  ~10 scored
                              ┗ ~6 high relevancy
⏱  ~3 min    💰  ~$0.01/run
```

</td>
</tr>
<tr>
<td width="50%" valign="top">

### Company Intel
For every job scoring ≥ 7/10: one command replaces 30 minutes of Googling. Funding stage, headcount, ML focus, risk flags, recent news — all synthesised into a structured JSON artifact.

```
score ≥ 7  →  Tavily (2 searches)
           →  Wikipedia fallback
           →  intel.json per job
💰  ~$0.02/job  ·  7-day cache
```

</td>
<td width="50%" valign="top">

### Gap Analysis
Semantic skill extraction across all accumulated JDs. Not keyword matching — the LLM reads your profile and reasons about capability equivalence. Tells you exactly what the market wants that you don't claim yet.

```
193 JDs  →  6-category extraction
         →  gap.json per job
         →  ranked frequency report
💰  ~$0.73 one-time  ·  incremental after
```

</td>
</tr>
</table>

---

## Quick start

**Prerequisites:** Python 3.12+, [uv](https://docs.astral.sh/uv/), OpenAI API key

```bash
# Clone and install
git clone https://github.com/shivangsingh26/dossier.git
cd dossier && uv sync

# Configure
cp .env.example .env        # add OPENAI_API_KEY + ANTHROPIC_API_KEY

# Build your profile (one-time)
uv run python scripts/run_persona_builder.py

# Run the full daily pipeline
uv run python run_dossier.py
```

That's it. One command runs discovery → watchlist → company intel → output.

---

## Pipeline

```
run_dossier.py  (master orchestrator — runs stages in sequence, isolated try/except)
│
├── Stage 0   Market Intel      weekly · discovers new AI/ML startups from funding news
│
├── Stage 1   Job Discovery     indeed + linkedin · 10 search terms · ~550 raw jobs
│   └── Pre-filter             service cos · short desc · seniority · support ops · PhD
│       └── LLM Scoring ×8    gpt-5.4-mini · company tier + job function as stated facts
│           └── Dedup          SQLite · skip rescoring across runs · ~40% cost reduction
│
├── Stage 2   Watchlist         70 target companies · Greenhouse/Lever/LinkedIn f_C=
│   └── Same pre-filter + scoring pipeline as Stage 1
│
├── Stage 3   Company Intel     score ≥ 7 · Tavily (2 queries) + Wikipedia · 7-day cache
│
└── Output    data/artifacts/{job_id}/
              ├── jd.txt            raw job description
              ├── score_card.json   score · tier · reason · urgency · skills gap
              ├── intel.json        funding · headcount · ML focus · risk flags
              └── gap.json          6-category skill match (v2) · has/missing split
```

**Run any stage independently:**

```bash
uv run python scripts/run_job_discovery.py  --hours 72 --min-score 7
uv run python scripts/run_watchlist.py      --min-score 5
uv run python scripts/run_company_intel.py  --min-score 7 --source both
uv run python scripts/run_gap_analysis.py   --top 15
uv run python scripts/run_market_intel.py   # run weekly
```

---

## Architecture

### Scoring

The pre-filter runs zero LLM calls. Only jobs that survive all gates reach the scoring executor.

```
is_hard_no()              service cos, IT staffing, job aggregators
description < 100 chars   no content = no signal
is_seniority_mismatch()   experience band from profile · penalises Senior / Staff / Intern
classify_job_function()   support_ops / pure_swe → skip
extract_years_required()  > exp_band max → hard reject
extract_degree_required() PhD → hard reject · Masters → soft penalty passed to LLM
is_job_seen(url)          SQLite dedup · already scored → skip
         │
         │  ~60% eliminated · zero LLM spend
         ▼
ThreadPoolExecutor ×8
  company_tier  ← from target_companies.json  (MAANG +4 · top_product +3 · ai_startup +2)
  job_function  ← from title keywords         (ml_ai / pure_swe / support_ops)
  years_req     ← extracted from JD           (within band = good fit fact)
  degree_req    ← extracted from JD           (BS = good · MS = note · PhD = rejected)
  └── gpt-5.4-mini → score 1–10 + reason + preferred_skills_missing
         │
  min_score gate + parent-company diversity cap (max 5 per company)
         │
         └── Rich terminal table · 11 columns · urgency · direct link
```

### Gap Analysis

Skill extraction uses **semantic matching**, not keyword lookup. Each JD is processed with the candidate's full profile summary so the LLM can reason about capability equivalence.

```
"LLMs" in JD  +  "LLM Pipeline Engineering [can_architect]" in profile
              →  candidate HAS this skill  ✓

"PyTorch" in JD  +  "Computer Vision [can_architect]: YOLO, RF-DETR, MobileNetV2"
                 →  candidate HAS this skill  ✓  (domain implies the tool)

"SQL" in JD  +  no SQL in profile aliases
             →  candidate MISSING this skill  ✗
```

Six categories extracted per JD: `technical` · `tools_platforms` · `domain` · `research_methods` · `behavioral` · `certifications`

Each job gets a `gap.json` (schema v2) that the resume agent will use to decide which bullets to lead with.

### Watchlist

```
For each of 70 target companies:
  ats_type == "greenhouse"  →  boards-api.greenhouse.io/v1/boards/{token}/jobs (free JSON)
  ats_type == "lever"       →  api.lever.co/v0/postings/{handle}?mode=json (free JSON)
  all others                →  LinkedIn f_C={company_id}
                                 resolve_linkedin_company_id(slug)
                                   → multi-pattern HTML extraction
                                   → cache: data/linkedin_company_ids.json
                                   → fallback: /about/ page
```

LinkedIn scraper uses `requests.Session()` for TCP reuse, exponential backoff on 429, ±40% jitter on all sleeps, and parallel description fetching with slot-based stagger.

---

## Company coverage

<table>
<tr>
<td valign="top" width="25%">

**MAANG &nbsp;(6)**

Google · Microsoft
Amazon · Meta
Apple · Netflix

</td>
<td valign="top" width="25%">

**Top Global Product &nbsp;(19)**

Uber · Stripe · Adobe · Atlassian
Salesforce · Intuit · NVIDIA · AMD
Qualcomm · PayPal · Databricks
Airbnb · LinkedIn · Coinbase
Wayfair · Target · Hotstar
Zoho · Walmart GTC

</td>
<td valign="top" width="25%">

**Top Indian Product &nbsp;(30)**

Flipkart · Zepto · Swiggy · Meesho
Razorpay · PhonePe · CRED · Dream11
Groww · Juspay · Browserstack
Freshworks · Postman · InMobi · Ola
Zomato · Myntra · MakeMyTrip
Delhivery · upGrad · BharatPe
Tata 1mg · Physics Wallah
Urban Company · Rapido · Lenskart
Porter · ixigo · OYO · MPL

</td>
<td valign="top" width="25%">

**AI Startups &nbsp;(10)**

Sarvam AI · Krutrim AI
Uniphore · Yellow.ai
Observe.AI · Vue.ai
Sprinklr · Darwinbox
Auric AI Labs · Haptik

</td>
</tr>
</table>

---

## LLM strategy

Cost is matched to task complexity. High-volume tasks get the cheapest reliable model. One-off quality tasks get better models. LaTeX work always goes to Claude.

| Task | Model | Why |
|---|---|---|
| Job scoring | `gpt-5.4-mini` | Runs on every job — cost is the constraint |
| Skill extraction (gap analysis) | `gpt-5.4-mini` | Batch processing across 200+ JDs |
| Company intel synthesis | `gpt-5.4-mini` | Noisy scraped data needs reasoning |
| Market intel extraction | `gpt-5.4-mini` | Structured JSON from news snippets |
| Persona builder interview | `gpt-5` | Conversational depth matters |
| Cold message drafting | `gpt-5` | Tone matching needs the best model |
| Cover letter generation | `claude-haiku-4-5` | Good writing, cost-efficient |
| Resume bullet rewriting | `claude-sonnet-4-6` | LaTeX-aware, highest precision |

All model names live in `config.py` only — changing any model is a one-line edit.

**Cost at scale:** A full week of daily discovery + watchlist runs ≈ $0.30. Gap analysis is one-time + incremental. Company intel ≈ $0.02/job with 7-day cache.

---

## Profile configuration

`profile/profile.json` is the single source of truth. Every agent reads from it at runtime — nothing is hardcoded. To use Dossier for a different person, replace this file.

```json
{
  "identity": {
    "name": "Your Name",
    "total_experience_months": 20,
    "location": "Bengaluru"
  },
  "target": {
    "roles": ["MLE-1", "AI Engineer", "Data Scientist"],
    "min_salary_lpa": 25,
    "switch_timeline_months": 8,
    "search_terms": ["Machine Learning Engineer", "LLM Engineer", "..."]
  },
  "skills": [
    {
      "skill": "LLM Pipeline Engineering",
      "depth": "can_architect",
      "market_aliases": ["LLM pipelines", "agentic AI", "GenAI systems"]
    }
  ],
  "known_gaps": ["LLM fine-tuning", "Distributed training"]
}
```

<details>
<summary><strong>Depth levels</strong></summary>

| Depth | Meaning |
|---|---|
| `can_teach` | Deep expertise — you can explain it to others |
| `can_architect` | Production experience — you've built systems with it |
| `can_use` | Working knowledge — you've used it in projects |

The gap analysis agent uses depth when reasoning about capability equivalence. `Computer Vision [can_architect]` implies PyTorch and Deep Learning, because you've built neural nets in production.

</details>

---

## Project structure

```
dossier/
│
├── agents/
│   ├── job_discovery.py          keyword search → pre-filter → LLM score → ranked output
│   ├── watchlist_agent.py        company-specific search (Greenhouse / Lever / LinkedIn)
│   ├── company_intel.py          Tavily + Wikipedia → structured intel per job
│   ├── market_intel_agent.py     funding news → new company discovery → route to pipeline
│   ├── gap_analysis.py           semantic skill extraction across all JDs → gap.json per job
│   └── persona_builder.py        terminal interview → profile.json
│
├── core/
│   ├── llm_client.py             unified interface: OpenAI + Anthropic · retry · token tracking
│   ├── linkedin_scraper.py       guest API · company ID resolver · Session · backoff · jitter
│   ├── file_vault.py             per-job artifact storage (jd.txt · scorecard · intel · gap)
│   ├── db.py                     SQLite dedup — is_job_seen / mark_job_seen
│   ├── intel_cache.py            company-level Tavily cache (7-day TTL · O(1) slug lookup)
│   ├── utils.py                  parse_json_response — safe LLM JSON parsing
│   └── logger.py                 structured logging · module-level loggers
│
├── prompts/
│   ├── job_scoring_system.txt    LLM scorer prompt
│   ├── skill_extract_system.txt  gap analysis extraction + semantic matching rules
│   └── ...
│
├── profile/
│   ├── profile.json              your persona — source of truth (gitignored)
│   ├── target_companies.json     70 companies: tier · slug · ATS type · funding metadata
│   └── exception_companies.json  companies we can't scrape + exact failure category
│
├── scripts/
│   ├── run_job_discovery.py      --hours  --min-score
│   ├── run_watchlist.py          --min-score  --location
│   ├── run_company_intel.py      --min-score  --source
│   ├── run_gap_analysis.py       --force  --min-score  --top
│   └── run_market_intel.py       (run weekly)
│
├── data/
│   ├── dossier.db                SQLite · seen job URLs
│   ├── gap_report.json           aggregate skill frequency report
│   ├── market_intel_queue.json   companies discovered by market intel (audit trail)
│   ├── intel_cache/              per-company Tavily cache (7-day TTL)
│   └── artifacts/{job_id}/
│       ├── jd.txt                raw job description
│       ├── score_card.json       score · tier · urgency · reason · skills gap
│       ├── intel.json            funding · headcount · ML focus · risk flags
│       └── gap.json              required/preferred skills · has/missing split (v2)
│
├── run_dossier.py                master orchestrator — one daily command
├── config.py                     singleton config · all model name constants
└── pyproject.toml                uv-managed · hatchling build backend
```

---

## Roadmap

| Feature | Status |
|---|---|
| Multi-source keyword discovery (Indeed + LinkedIn) | ✅ Done |
| Two-pass scoring — rule-based pre-filter + parallel LLM (×8) | ✅ Done |
| Ground-truth company tier lookup (70 companies, verified) | ✅ Done |
| Profile-driven seniority + experience gating | ✅ Done |
| Parent-company dedup (Amazon.com + Amazon Science = 1 slot) | ✅ Done |
| Watchlist agent — Greenhouse / Lever / LinkedIn `f_C=` | ✅ Done |
| LinkedIn company ID resolver with disk cache | ✅ Done |
| Company intel agent — Tavily + Wikipedia + 7-day cache | ✅ Done |
| SQLite dedup — skip rescoring across runs | ✅ Done |
| Master orchestrator — `run_dossier.py` | ✅ Done |
| Market intel agent — funding news → company discovery | ✅ Done |
| Gap analysis agent — semantic extraction across 193 JDs | ✅ Done |
| **Resume agent** — LaTeX bullet rewriting via Claude Sonnet | 🔨 Next |
| Referral finder — people worth reaching out to at target companies | 📋 Planned |
| Cold outreach generator — personalised LinkedIn DM + email | 📋 Planned |
| Telegram alerts — URGENT jobs pushed within minutes of posting | 📋 Planned |
| LTR scorer — LightGBM trained on apply/response signal | 🔮 Future |

---

## Product tiers

Dossier is built in tiers. Each tier is independently useful.

| Tier | What you get | State |
|---|---|---|
| **Dossier Lite** | Keyword discovery · Indeed + LinkedIn · LLM scoring | ✅ Built |
| **Dossier Pro** | + Watchlist (70 companies) · company intel · orchestrator | ✅ Built |
| **Dossier Max** | + Market intel · gap analysis · referral finder · resume agent | 🔨 Building |

---

<div align="center">

Built for engineers who want to work at places worth working at.

</div>
