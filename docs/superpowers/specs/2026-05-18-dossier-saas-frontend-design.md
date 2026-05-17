# Dossier — SaaS Frontend + Backend Revamp — Design Spec

> Date: 2026-05-18
> Author: Shivang Singh (with Claude)
> Status: Approved by user (2026-05-18). Ready for implementation plan.
>
> Supersedes: `dashboard.py` (Streamlit). Streamlit kept running until frontend reaches feature parity (post-M4), then deleted.

---

## 1. Goal

Turn Dossier from a single-user Streamlit dashboard into a multi-tenant SaaS web product.

End-state for this spec (post-M5):
- Public marketing site (hero, pricing, sign-in, sign-up).
- Authenticated multi-user web app: persona onboarding, job inbox, agent runs gated by a credit + tier system.
- Admin console: approve signups, manage tiers/credits, edit shared config, trigger pipelines.
- Long-running pipelines decoupled from HTTP via a background worker + SSE/polling for progress.
- All built free-tier-only (no paid infra commitments). LLM costs continue to be paid by user's own OpenAI/Anthropic keys.

Out of scope for this spec (deferred):
- Stripe / real payments (M11, post-validation).
- Postgres migration (deferred until SaaS goes public).
- Mobile apps.

---

## 2. Approved Decisions (from brainstorming session)

| Topic | Decision |
|---|---|
| Frontend framework | Next.js 16 (App Router, RSC, TypeScript strict) |
| UI base | shadcn/ui + Tailwind v4 + motion (framer) |
| Component sources | 21st.dev, ui-layouts, AI Elements (for chat-style quiz) |
| Forms | react-hook-form + zod |
| Data fetching | TanStack Query + RSC where applicable |
| State | RSC + Query (no global store) |
| Auth | Clerk (user + admin via `publicMetadata.role`) |
| Backend framework | FastAPI (Python 3.12), wraps existing Python SDK |
| Background work | Standalone Python worker process polling SQLite (no Redis) |
| Database | SQLite per-user (existing `data/{user}/dossier.db` preserved) + new `accounts.db` for auth/credits/runs |
| Hosting | Local dev only for now. Production plan: Vercel free + Fly.io free worker (or self-host). |
| Brand theme | Warm Mocha — dark-first |
| Logo | Split-D monogram (primary mark) + Fraunces italic wordmark |
| Persona builder UX | 4-step wizard (Upload → Targets → Chat quiz → Review) |
| Pipeline trigger | Manual "Run now" button (credit-gated) + scheduled cron daily (M5+) |
| Credit model | Per-agent invocation |
| Tier model | Lite (free, 50 cr, discovery only) / Pro (₹999 intent, 500 cr, +watchlist+intel+gap) / Max (₹2,999 intent, 2,000 cr, all agents) |
| Payment | Stubbed: free + "Upgrade" CTA → waitlist. Real Stripe in M11. |
| Existing 4 users | Pre-seeded in Clerk with Max tier, mapped to existing `data/{user}/` folders |

---

## 3. Brand System

### 3.1 Palette (Warm Mocha)

```
bg:          #1a1410   /* deep mocha — page bg */
surface:     #251d18   /* card / panel */
surface-2:   #15100d   /* deeper than bg — sidebar/nav */
border:      #2d2419
border-2:    #44342a
text:        #f5ebe0   /* warm cream */
text-muted:  #a89589
text-subtle: #7a695a

primary:     #f97316   /* peach — CTAs, accents, highlights */
primary-hov: #ea580c
primary-soft:#fdba74   /* "good" tier hover */

secondary:   #4ade80   /* mint — success, "applied", best-match */
secondary-soft: rgba(74,222,128,0.15)

warning:     #fbbf24
danger:      #ef4444

/* Score scale */
score-9:     #4ade80   /* strong fit */
score-7:     #1d4ed8   /* good fit */
score-5:     #fdba74   /* fair fit */
score-low:   #ef4444   /* weak fit */
```

### 3.2 Typography

```
display: 'Fraunces Variable', Georgia, serif   /* italic 500 for emphasis */
body:    'Geist Variable', 'Inter', sans-serif
mono:    'Geist Mono Variable', monospace      /* code, numbers, credits */
```

Scale: `12 / 13 / 14 / 16 / 18 / 22 / 28 / 36 / 48`

Headlines use Fraunces. Body, UI labels, tables use Geist. Numbers (credits, scores, prices) use Geist Mono for tabular alignment.

### 3.3 Radius + Shadow

```
radius:    sm 6 / md 8 / lg 10 / xl 14 / 2xl 18
shadow-card:   0 1px 3px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.04)
shadow-hover:  0 4px 22px rgba(249,115,22,0.14)
shadow-modal:  0 24px 60px rgba(0,0,0,0.6)
```

### 3.4 Logo

**Primary mark** = Split-D monogram:
- Outer circle: `#f5ebe0` stroke 3px (light bg) or `#1a1410` (dark bg)
- Left half of D: `#f97316` peach
- Right half of D (arc): `#4ade80` mint
- SVG paths (canonical):
  ```
  Outer: <circle cx=50 cy=50 r=46 fill=none stroke=text stroke-width=3>
  Peach: <path d="M 30 22 L 30 78 L 56 78 A 28 28 0 0 0 56 22 Z" fill=#f97316>
  Mint:  <path d="M 56 22 A 28 28 0 0 1 56 78 L 56 50 Z" fill=#4ade80>
  ```

**Wordmark** = `Dossier` in Fraunces italic 500, with a peach `.` period appended (`Dossier.`).

**Full lockup** = mark + wordmark side by side, mark 24-44px depending on context.

Usage:
- Favicon: mark only (16/32/180px PNG/SVG)
- App icon: mark on `#1a1410` rounded-square background
- Sidebar collapsed: mark only on `surface-2`
- Sidebar expanded: full lockup
- Marketing hero: large wordmark, mark optional
- Footer / email signature: full lockup

---

## 4. Repo Structure (post Milestone 0)

```
dossier/                              # repo root
├── sdk/                              # Python package (existing code moved here)
│   ├── pyproject.toml                # name = "dossier-sdk", uv-managed
│   ├── .venv/                        # own venv
│   ├── src/dossier_sdk/              # importable package
│   │   ├── __init__.py
│   │   ├── config.py                 # was /config.py
│   │   ├── core/                     # was /core/
│   │   ├── agents/                   # was /agents/
│   │   ├── prompts/                  # was /prompts/
│   │   └── orchestrator.py           # was /run_dossier.py (functions only)
│   ├── scripts/                      # CLI scripts unchanged behavior
│   └── tests/
│
├── backend/                          # FastAPI service (new)
│   ├── pyproject.toml                # name = "dossier-api", depends on dossier-sdk
│   ├── .venv/                        # own venv
│   ├── src/dossier_api/
│   │   ├── main.py                   # FastAPI app
│   │   ├── routers/                  # auth, persona, jobs, pipeline, admin
│   │   ├── services/                 # wraps dossier_sdk calls
│   │   ├── models/                   # pydantic schemas
│   │   ├── deps.py                   # Clerk JWT verify, tier+credit gates
│   │   ├── db.py                     # accounts.db init + migrations
│   │   └── workers/                  # pipeline_worker.py
│   └── tests/
│
├── frontend/                         # Next.js 16 (new)
│   ├── package.json                  # pnpm-managed
│   ├── app/
│   │   ├── (marketing)/
│   │   │   ├── layout.tsx
│   │   │   ├── page.tsx              # hero landing
│   │   │   └── pricing/page.tsx
│   │   ├── (auth)/
│   │   │   ├── sign-in/[[...sign-in]]/page.tsx
│   │   │   └── sign-up/[[...sign-up]]/page.tsx
│   │   ├── (app)/
│   │   │   ├── layout.tsx            # sidebar shell, Clerk gate
│   │   │   ├── dashboard/page.tsx    # post-login home
│   │   │   ├── onboarding/page.tsx   # persona wizard
│   │   │   ├── jobs/page.tsx
│   │   │   ├── jobs/[jobId]/page.tsx
│   │   │   ├── watchlist/page.tsx    # M6
│   │   │   ├── gaps/page.tsx         # M7
│   │   │   ├── referrals/page.tsx    # M9
│   │   │   ├── resume/page.tsx       # M8
│   │   │   ├── market/page.tsx       # M10
│   │   │   └── settings/page.tsx
│   │   ├── (admin)/
│   │   │   └── admin/page.tsx        # M5, role-gated
│   │   └── api/                      # webhook endpoints (clerk → backend proxy)
│   ├── components/ui/                # shadcn primitives + 21st.dev blocks
│   ├── components/dossier/           # custom (JobCard, CreditPill, PersonaWizard, KpiStrip)
│   ├── lib/
│   │   ├── api.ts                    # typed FastAPI client
│   │   ├── clerk.ts                  # client helpers
│   │   └── theme.ts                  # mocha tokens
│   └── styles/globals.css            # Tailwind v4 + fonts
│
├── data/                             # unchanged — per-user dossier.db, artifacts
├── profile/                          # unchanged — per-user folders
├── helper_files/                     # unchanged
├── docs/
│   └── superpowers/
│       ├── specs/                    # this file lives here
│       └── milestones/               # M0.md, M1.md, … (per-milestone trackers)
├── frontend-todo.txt                 # live task tracker (synced with milestones)
├── dashboard.py                      # KEPT working through M3; deleted after M4
├── pyproject.toml                    # root: thin workspace meta (optional)
└── README.md
```

Each of `sdk/`, `backend/`, `frontend/` has independent install. `backend/pyproject.toml` declares `dossier-sdk` as a local path dependency (`{path = "../sdk", develop = true}`).

---

## 5. Tech Stack (Locked)

| Layer | Choice | Reason |
|---|---|---|
| Frontend framework | Next.js 16 (App Router, RSC) | Latest, free Vercel hobby |
| UI primitives | shadcn/ui + Tailwind v4 | Trending, full ownership |
| Component sources | 21st.dev, ui-layouts, AI Elements | Copy-paste blocks |
| Animation | motion (framer) | Standard for shadcn ecosystem |
| Forms | react-hook-form + zod | Type-safe wizard validation |
| Data | TanStack Query + RSC | Background revalidation for credits/jobs |
| Auth | Clerk free (10K MAU) | User + admin via metadata, native Next.js |
| Backend | FastAPI (Python 3.12) + uvicorn | Wraps existing SDK |
| Backend deps | pydantic v2, httpx, clerk-sdk-python, sse-starlette, fasteners | All free |
| Worker | Standalone Python process (asyncio loop) polling SQLite | No Redis, free |
| DB (per-user) | SQLite (unchanged from current `data/{user}/dossier.db`) | Pipeline disruption = zero |
| DB (auth/credits) | New `accounts.db` SQLite at `data/accounts.db` | Free, simple |
| Lang | TypeScript strict (frontend), Python 3.12 + ruff (backend) | Non-negotiable |
| Package mgmt | pnpm (frontend), uv (sdk + backend) | Both fastest |
| Hosting (later) | Vercel hobby (free) + Fly.io free tier (3 small VMs) for backend+worker | Free |
| Errors (later) | Sentry free 5K events/mo | Free |

---

## 6. Auth Flow (Clerk)

```
┌─────────────┐    sign up     ┌──────────────┐    webhook     ┌──────────────┐
│  marketing  │ ──────────────→│    Clerk     │ ─────────────→ │ FastAPI hook │
│  page (/)   │                │  (hosted UI) │                │   /webhooks/clerk
└─────────────┘                └──────────────┘                └──────┬───────┘
                                                                      │ create row
                                                                      ▼
                                                              ┌─────────────────┐
                                                              │  accounts.db    │
                                                              │  user_id PK     │
                                                              │  clerk_id       │
                                                              │  email          │
                                                              │  data_user_slug │
                                                              │  tier (lite)    │
                                                              │  credits (100)  │  /* signup gift */
                                                              │  status (pending)│
                                                              │  created_at     │
                                                              └─────────────────┘
```

**Roles via Clerk publicMetadata:**
```json
{ "role": "user" | "admin", "tier": "lite" | "pro" | "max" }
```

**Frontend:**
- `useUser()` from `@clerk/nextjs` reads role/tier.
- Admin nav items conditionally rendered.
- Tier-locked features show a "Upgrade to Pro" overlay instead of being hidden.

**Backend:**
- Every endpoint (except `/health` and `/webhooks/clerk`) verifies Clerk session JWT via `clerk-sdk-python.authenticate_request`.
- `Depends(get_current_user)` returns the `accounts.db` row + tier + remaining credits.
- Admin endpoints additionally check `role == "admin"`.

**Existing 4 users (`shivang`, `krishna`, `anushthan`, `sambhav`):**
- Seed script (`backend/scripts/seed_existing_users.py`) — **run once as part of M2 backend bootstrap**:
  1. Read existing folder names from `data/` and `profile/`.
  2. For each existing user, create Clerk user via Clerk Backend API with email pre-filled (emails maintained in a `seed_users.json` config kept out of git).
  3. Set `publicMetadata = {role: "admin" if user == "shivang" else "user", tier: "max"}`.
  4. Insert `accounts.db` row with `data_user_slug` matching existing folder name, `credits = 99999` (effectively unlimited for admins/seeded), `status = active`.
  5. Send Clerk magic-link email for first login.
- Idempotent: re-running skips users whose `clerk_id` already exists in `accounts.db`.

**New signups:**
- Land in `accounts.db` with `status = pending`, `tier = lite`, `credits = 100`.
- Admin sees them in `/admin` → "Approve" button flips `status = active`.
- Until approved, login shows "Your account is pending review" screen.

---

## 7. Credit + Tier System

### 7.1 Credit costs per agent action

| Action | Credits | Allowed tiers | Note |
|---|---|---|---|
| Job discovery (single run, all sources) | **5** | Lite, Pro, Max | ~$0.10 actual LLM |
| Watchlist scan (all target companies) | **8** | Pro, Max | More fetches |
| Company intel (per company) | **3** | Pro, Max | Tavily + LLM |
| Gap analysis (single run) | **4** | Pro, Max | Batch extract |
| Resume tailor (per job) | **12** | Max only | Claude Sonnet 3-pass |
| Cover letter (per job) | **4** | Max only | Claude Haiku 1-pass |
| Referral finder (per job) | **6** | Max only | LinkedIn + Tavily search |
| Cold message draft (per contact) | **2** | Max only | Single LLM call |
| Market intel scan (daily) | **5** | Max only | Funding news + dedupe |

### 7.2 Tier matrix

| Tier | Price (intent) | Monthly credits | Agents allowed |
|---|---|---|---|
| **Lite** (free) | ₹0 | 50/month | Job discovery only |
| **Pro** | ₹999 intent | 500/month | + Watchlist, Company intel, Gap analysis |
| **Max** | ₹2,999 intent | 2,000/month | + Resume tailor, Cover letter, Referral finder, Cold message, Market intel |

- Signup gift: **100 one-time credits** regardless of tier (lets free users try one Max action like a single resume tailor).
- Monthly credits reset on the 1st (or 30 days from signup for new users).
- **Stub payment:** "Upgrade" CTA captures email + chosen tier → `waitlist` table. Admin sees waitlist, manually grants tier change.

### 7.3 Credit gate flow

```
POST /pipeline/run {agents: [...]}
  ↓
1. Verify Clerk JWT → load user
2. For each requested agent:
     a. Check tier allows it. If not → 403 + "Upgrade to {required_tier}"
     b. Sum credit cost
3. If total > credits remaining → 402 + "Insufficient credits"
4. Atomic: deduct credits, insert pipeline_run rows (status=queued)
5. Insert credit_log entry (reason="run:disc+watch")
6. Return 202 + run IDs
  ↓
Worker picks up run.
If agent fails:
  → mark run status=failed
  → refund credits (insert credit_log delta=+N reason="refund:disc:failure")
```

### 7.4 Schema (new — `data/accounts.db`)

```sql
CREATE TABLE accounts (
    user_id           TEXT PRIMARY KEY,        -- internal uuid
    clerk_id          TEXT UNIQUE NOT NULL,
    email             TEXT UNIQUE NOT NULL,
    data_user_slug    TEXT UNIQUE NOT NULL,    -- maps to data/{slug}/ folder
    role              TEXT NOT NULL DEFAULT 'user',  -- user | admin
    tier              TEXT NOT NULL DEFAULT 'lite',  -- lite | pro | max
    status            TEXT NOT NULL DEFAULT 'pending', -- pending | active | suspended
    credits           INTEGER NOT NULL DEFAULT 100,
    credits_reset_at  TEXT NOT NULL,           -- next monthly reset
    created_at        TEXT NOT NULL,
    last_login_at     TEXT
);

CREATE TABLE credit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   TEXT NOT NULL,
    delta     INTEGER NOT NULL,                 -- negative = deduction, positive = refund/topup
    reason    TEXT NOT NULL,                    -- "run:disc", "refund:disc:failure", "monthly_reset", "admin_topup"
    run_id    TEXT,                             -- nullable
    at        TEXT NOT NULL
);

CREATE TABLE pipeline_runs (
    run_id           TEXT PRIMARY KEY,          -- uuid
    user_id          TEXT NOT NULL,
    parent_run_id    TEXT,                      -- null for parent run
    agent            TEXT NOT NULL,             -- "parent" | discovery | watchlist | company_intel | ...
    status           TEXT NOT NULL,             -- queued | running | completed | failed
    credits_cost     INTEGER NOT NULL,
    credits_refunded INTEGER DEFAULT 0,
    started_at       TEXT,
    finished_at      TEXT,
    progress_json    TEXT,                      -- {steps: [{name, status, duration_ms, log_tail}]}
    error            TEXT,
    output_summary_json TEXT                    -- {jobs_added: 12, score_distribution: {...}}
);
CREATE INDEX idx_pipeline_runs_user_status ON pipeline_runs(user_id, status);
CREATE INDEX idx_pipeline_runs_parent ON pipeline_runs(parent_run_id);

CREATE TABLE waitlist (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT NOT NULL,
    desired_tier TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    fulfilled    INTEGER NOT NULL DEFAULT 0
);
```

---

## 8. Long-Running Pipeline Architecture

### 8.1 Problem

Observed: a single `run_dossier` execution took 2,000 seconds (watchlist + discovery + intel + market all ran). HTTP synchronous request cannot survive that. Even local-only dev is fragile (tab reload = lost run).

### 8.2 Networking primer (for reference)

| Layer | Default timeout |
|---|---|
| Browser fetch | None hard, but user abandons ~30s |
| Nginx reverse proxy | 60s |
| Cloudflare free | 100s |
| Vercel serverless | 60s hobby / 300s pro |
| FastAPI/uvicorn | None (but upstream cuts it) |

**Implication:** Pipeline must run **out of band** of the HTTP request.

### 8.3 Solution — async job pattern

```
Frontend                FastAPI                  Worker process              SQLite
   │                       │                          │                         │
   │  POST /pipeline/run   │                          │                         │
   │  {agents:[disc,intel]}│                          │                         │
   ├──────────────────────►│                          │                         │
   │                       │ deduct credits           │                         │
   │                       │ insert run (queued)      │                         │
   │                       ├──────────────────────────┼────────────────────────►│
   │  202 Accepted         │                          │                         │
   │  {parent_run_id:"p1", │                          │                         │
   │   children:[{...}]}   │                          │                         │
   │◄──────────────────────┤                          │                         │
   │                       │                          │ poll DB every 5s        │
   │                       │                          ├────────────────────────►│
   │                       │                          │ execute pipeline        │
   │                       │                          │ write progress steps    │
   │                       │                          ├────────────────────────►│
   │                       │                          │                         │
   │  GET /runs/p1/stream  │                          │                         │
   │  (SSE)                │                          │                         │
   ├──────────────────────►│ read run state           │                         │
   │  event: progress      ├──────────────────────────┼────────────────────────►│
   │  data: {step:"disc",  │                          │                         │
   │    status:"done"}     │                          │                         │
   │◄──────────────────────┤                          │                         │
   │  event: complete      │ marks run done           │                         │
   │◄──────────────────────┤                          │                         │
```

### 8.4 Components

**`backend/src/dossier_api/workers/pipeline_worker.py`** — separate Python process:

```python
"""
Background worker. Polls accounts.db for queued runs, executes them.
Restart-safe: state in DB, not memory.
Run via: uv run python -m dossier_api.workers.pipeline_worker
"""
async def main():
    while True:
        run = pick_next_queued_run()  # atomic SELECT...UPDATE status=running
        if run is None:
            await asyncio.sleep(5)
            continue
        try:
            await execute_pipeline(run)   # calls dossier_sdk agents
            mark_completed(run, summary)
        except Exception as e:
            mark_failed(run, str(e))
            refund_credits(run)
```

**SSE endpoint** `GET /pipeline/runs/{run_id}/stream`:
- Reads `pipeline_runs` table every 1s
- Yields `event: progress` lines as steps complete
- Closes when `status in ('completed','failed')`
- Frontend uses native `EventSource`, auto-reconnects on disconnect
- Resume-safe: frontend stores `last-event-id` (step index)

**Polling fallback** `GET /pipeline/runs/{run_id}` (plain JSON):
- For corporate proxies that block SSE
- Frontend tries SSE first, falls back to 2s poll on connection error

### 8.5 Split-agent runs

Pipeline request = **one parent + N child runs**.

```
POST /pipeline/run
{ "agents": ["discovery", "watchlist", "company_intel", "market_intel"] }

Response 202:
{
  "parent_run_id": "p_abc",
  "children": [
    {"run_id": "c_disc",   "agent": "discovery",     "credits_cost": 5},
    {"run_id": "c_watch",  "agent": "watchlist",     "credits_cost": 8},
    {"run_id": "c_intel",  "agent": "company_intel", "credits_cost": 3},
    {"run_id": "c_market", "agent": "market_intel",  "credits_cost": 5}
  ],
  "total_credits_deducted": 21,
  "estimated_seconds": 1800
}
```

Behavior:
- Worker picks children one at a time (sequential per user, to avoid API rate limits).
- Each child writes progress independently.
- Parent run `status` = `completed` only when all children terminal (`completed` or `failed`).
- **Per-agent refund:** if `c_watch` fails (e.g. LinkedIn rate-limited), only its 8 credits are refunded. Others stay deducted.
- UI: parent progress bar = `% children completed`; expandable rows show per-agent status, duration, output summary, error message.

Concurrency rules:
- Per-user concurrency = 1 (sequential children).
- Cross-user concurrency unbounded (multiple worker instances may run later).

---

## 9. FastAPI Surface (Key Endpoints)

```
# System
GET    /health
POST   /webhooks/clerk

# Current user
GET    /me                          # { user, tier, credits, status, data_user_slug }

# Persona
POST   /persona/upload-pdf          # multipart: { resume?, linkedin? }
POST   /persona/questionnaire       # JSON of form answers (work, locations, salary, etc.)
POST   /persona/quiz-message        # SSE stream — chat-style 12-Q quiz; each POST = one turn
GET    /persona                     # current profile.json
PATCH  /persona                     # edit fields (review step)
POST   /persona/finalize            # trigger persona_builder synthesis → profile.json

# Jobs
GET    /jobs?status=&min_score=&source=&search=
GET    /jobs/{id}                   # full + scorecard + gap + intel + jd_text
POST   /jobs/{id}/status            # body: { status: "Interested" | ... }
POST   /jobs/{id}/notes
POST   /jobs/{id}/tailor-resume     # 12 credits, Max only
POST   /jobs/{id}/find-referrals    # 6 credits, Max only

# Pipeline
POST   /pipeline/run                # body: { agents: ["discovery", ...] }, returns 202
GET    /pipeline/runs?limit=20      # recent runs for current user
GET    /pipeline/runs/{id}          # snapshot (polling)
GET    /pipeline/runs/{id}/stream   # SSE progress

# Admin (role=admin only)
GET    /admin/users
POST   /admin/users/{id}/approve    # status: pending → active
POST   /admin/users/{id}/tier       # body: { tier }
POST   /admin/users/{id}/credits    # body: { delta, reason }
POST   /admin/users/{id}/suspend
GET    /admin/waitlist
POST   /admin/waitlist/{id}/fulfill
GET    /admin/companies             # read target_companies.json
PUT    /admin/companies             # write (file-lock)
POST   /admin/pipeline/run          # trigger for any user_id
```

Auth gates:
- All routes except `/health` and `/webhooks/clerk` require valid Clerk JWT.
- All `/admin/*` additionally require `role == "admin"`.
- All `/pipeline/run` and `/jobs/{id}/tailor-resume`, `/find-referrals` additionally pass through credit + tier gate.

---

## 10. Frontend Routes + Components

### 10.1 Route map

```
(marketing)
  /                       Hero landing
  /pricing                3-tier table

(auth)
  /sign-in                Clerk hosted (themed)
  /sign-up                Clerk hosted (themed)

(app)   [protected: requires sign-in]
  /dashboard              Post-login home (KPIs + recent runs + quick actions)
  /onboarding             Persona wizard — 4 steps, auto-redirects here if persona missing
  /jobs                   Job inbox (KPI + tabs + cards + sticky detail pane)
  /jobs/[jobId]           Deep route (same view, jobId pre-selected) for sharing
  /watchlist              M6 — separate tab/view for watchlist-source jobs
  /gaps                   M7 — skill frequency vs profile
  /referrals              M9 — contacts per job
  /resume                 M8 — generated PDFs library
  /market                 M10 — funded-startup alerts
  /settings               Account, theme, persona-edit shortcut, danger zone

(admin) [protected: requires role=admin]
  /admin                  User list, approvals, tier mgmt, pipeline trigger, companies editor
```

### 10.2 Key custom components (`components/dossier/`)

| Component | Used in | Purpose |
|---|---|---|
| `<Sidebar>` | `(app)/layout.tsx` | Collapsible nav; tier locks visible (PRO/MAX badges next to gated items) |
| `<CreditPill>` | header on all app pages | `⚡ 437 / 500 credits` with hover popover showing recent debits |
| `<RunButton>` | dashboard, jobs page | "Run discovery — 5 credits" → confirms → calls `/pipeline/run` |
| `<PipelineProgress>` | overlay/modal | Connects to SSE, shows parent + child agent status, log tail |
| `<JobCard>` | /jobs | Single job — score, status pill, source, freshness, click → select |
| `<JobDetail>` | /jobs sticky panel | Header, status buttons, why-match, skill gap, action buttons (tailor resume, find referrals) |
| `<KpiStrip>` | /dashboard, /jobs | 4-card row (active / strong / interested / applied) |
| `<PersonaWizard>` | /onboarding | 4-step stepper, holds state in URL hash, calls FastAPI per step |
| `<ChatQuiz>` | step 3 of wizard | AI Elements based chat; one Q at a time; persists answers |
| `<TierGate>` | feature wrappers | If tier insufficient, render upsell overlay instead of feature |
| `<AdminUserTable>` | /admin | TanStack Table with approve/suspend/tier-change actions |
| `<JsonEditor>` | /admin | For target_companies.json edits (Monaco-lite or simple textarea + validation) |

### 10.3 Data-fetching pattern

- Public pages (marketing/pricing): RSC, statically rendered.
- App shell (`(app)/layout.tsx`): RSC fetches `/me` via Clerk session token → passes user+tier+credits down via context.
- Job inbox: client component using TanStack Query — `useQuery(['jobs', filters])`.
- Pipeline progress: client EventSource subscription, falls back to polling.
- Mutations (status change, notes save): `useMutation` with optimistic update + invalidate.

---

## 11. Milestone Breakdown

Each milestone gets its own tracker file at `docs/superpowers/milestones/M{N}.md`. `frontend-todo.txt` mirrors active tasks for hand-off to fresh sessions.

| # | Title | Scope summary | Done when |
|---|---|---|---|
| **M0** | Repo restructure + SDK packaging | Move existing Python into `sdk/`, package as `dossier-sdk`. Create empty `backend/` + `frontend/`. **Update `dashboard.py` + `run_dossier.py` imports** to point at `dossier_sdk.*`. | `uv pip install -e ./sdk` works; `python dashboard.py` still works; `python run_dossier.py --user shivang --mode quick` still works; existing tests pass. |
| **M1** | Frontend skeleton + Clerk auth + theme | Next.js 16 init, Tailwind v4, shadcn, Fraunces + Geist fonts, mocha tokens, Clerk install + theming, marketing layout, hero landing page, sign-in/sign-up, post-login empty dashboard shell with sidebar + CreditPill. | Visit `/`, sign up, land on `/dashboard` shell with sidebar + credit pill rendering. |
| **M2** | Backend skeleton + Clerk webhook + accounts DB + worker | FastAPI app, JWT middleware, `/health` + `/me`, signup webhook → `accounts.db` row, seed script for existing 4 users, worker process boilerplate. | New signup creates pending row; existing 4 sign in; worker starts and idles. |
| **M3** | Persona builder wizard | 4-step wizard (Upload → Targets → Chat quiz → Review). FastAPI `/persona/*` endpoints. SSE chat quiz. `persona_builder.py` synthesis triggered via worker. Profile saved. | New user completes onboarding end-to-end and sees their generated persona JSON. |
| **M4** | Job inbox page + pipeline run | `/jobs` page complete with KPI, tabs, JobCard, JobDetail, status changes, notes. `RunButton` → `/pipeline/run` (discovery agent, 5 credits) → SSE progress overlay → jobs refresh. | Click "Run discovery" → credits drop → progress bar → jobs appear → review/star/apply works. |
| **M5** | Admin dashboard | `/admin` route, role-gated. User list, approve pending, change tier, top-up credits, trigger pipeline for any user, edit `target_companies.json` via JSON editor. Waitlist view. | Admin approves a pending user; user can log in and reach `/jobs`. |
| **M6** | Watchlist + Company intel | Pro-tier agents. `/watchlist` page (separate from /jobs). Company intel modal on each JobCard. Tier gate on `RunButton`. | Pro user runs watchlist + sees intel popover. Lite user sees upgrade overlay. |
| **M7** | Gap analysis page | `/gaps` route. Bar chart of skill frequency vs profile. Pro feature. | Gap report renders for shivang's data. |
| **M8** | Resume tailor + cover letter | "Tailor for this job" button on JobCard. Generates LaTeX + PDF. Preview pane. Max tier. | Generate + download a tailored resume PDF. |
| **M9** | Referral finder + cold message | Contact list per job. Message editor. Max tier. | Referral candidates surface with draft messages. |
| **M10** | Market intel feed | `/market` page with new-funding alerts. Max tier. | Live feed of funded AI/ML startups. |
| **M11** | Payment integration | Stripe checkout, real subscriptions, credit top-ups. Deferred until paying-intent validated. | Real money flows. |

**MVP = M0 → M4** (≈ first usable web product). Stop, dogfood, then M5 → M10 incrementally.

---

## 12. Non-Goals + Constraints

- **No money spent on infra during dev.** All choices Free tier only. (LLM API spend continues from user's own OpenAI/Anthropic keys — out of scope for this spec.)
- **No Postgres migration** until SaaS goes public (deferred indefinitely).
- **No Redis/Celery.** SQLite + Python worker only.
- **No real payments** until M11.
- **No multi-region.** Single FastAPI instance, single worker.
- **No mobile apps.** Web-only.
- **No public auto-apply.** User decides every action; agent only prepares.
- **No LinkedIn scraping.** Same constraint as existing pipeline.
- **Don't break the existing CLI** at any point. `python run_dossier.py --user shivang` must keep working through every milestone until explicitly retired post-M4.

---

## 13. Risks + Mitigations

| Risk | Mitigation |
|---|---|
| Existing pipeline imports break during M0 restructure | Restructure in a feature branch; run full test suite before merge. Keep `dashboard.py` working as smoke check. |
| Clerk free tier limits (10K MAU) | Plenty for closed beta. Migrate to paid Clerk or Auth.js if exceeded. |
| SSE blocked by user's network | Polling fallback at 2s interval — auto-detected on EventSource error. |
| Long pipeline (2000s) blocks worker | Per-user concurrency=1 is acceptable. Worker handles other users in parallel later (M5+). Per-agent timeout (e.g. 600s for discovery, 1500s for watchlist) → mark failed + refund. |
| Credit refund race conditions | All credit mutations atomic in SQLite transactions. `credit_log` is append-only ledger of truth; current balance is materialized but reconcilable. |
| `target_companies.json` concurrent admin edits | File lock via `fasteners.InterProcessLock`. Admin UI warns "another admin is editing". |
| PDF upload abuse | 10MB max, parsed server-side via `pymupdf`, files stored under `data/{user}/raw/` with original filename hashed. |
| Lost runs on worker crash | Worker process supervised by systemd/supervisor (in prod). In dev, runs marked `running > 30min ago` are reaped + refunded by a cleanup job. |
| LLM cost spikes from credit-bypassed admin | Admin pipeline triggers also debit credits (set to 0 by default for admins). Cost visibility in admin dashboard. |
| Existing user data folder name collision (e.g. user signs up with email "shivang@..." but slug already taken) | Seed script reserves the 4 existing slugs. New signups get `data_user_slug = clerk_id` (uuid-based, no collision possible). |

---

## 14. Open Items (Not Blocking)

- Email transactional sending (magic link content, approval emails, monthly credit reset notice). Use Clerk's built-in email or Resend free tier (3K/mo).
- Analytics: PostHog free tier (1M events/mo) — add in M5+ for funnel measurement.
- Logging: keep Python `logging` + JSON output. Send to Sentry free tier when deploying.
- Dark/light toggle: ship dark-only for v1; light mode (cream palette from Theme 1) only for shared link previews (OG images). Reassess after launch.
- Mobile responsive: design dark-mode-first, but every page must work at 375px width by M4. Wizard + dashboard tested in Chrome DevTools mobile mode.
- i18n: English only for v1.

---

## 15. Acceptance Criteria (per milestone)

Each milestone's `M{N}.md` file lists granular task checklist. High-level acceptance:

- **M0**: `pytest` passes from `sdk/`; `dashboard.py` opens at localhost:8501; `import dossier_sdk` works from python REPL.
- **M1**: Visit `localhost:3000`, click "Sign up", complete Clerk flow, redirected to `/dashboard` showing sidebar + brand mark + "Welcome" heading.
- **M2**: New signup → row in `accounts.db` with `status=pending`. Existing user `shivang` can log in. `pipeline_worker.py` running shows "idle, no queued runs" log line.
- **M3**: Fresh signup → guided through 4-step wizard → `profile/{slug}/profile.json` exists and is valid persona schema.
- **M4**: With active user, click "Run discovery" → credits 100 → 95 → progress UI → 4 new jobs visible → can star/apply/note.
- **M5**: Admin logs in → sees `/admin` → sees pending users → clicks approve → that user can now log in.

---

## 16. References

- Existing positioning: `helper_files/PRODUCT_POSITIONING.md`
- Existing business value: `helper_files/BUSINESS_VALUES.md`
- Existing progress snapshot: `current_progress.md`
- Streamlit dashboard (to be replaced post-M4): `dashboard.py`
- Hero block reference (from user): `frontend-prompt.txt`
- Brainstorm session mockups: `.superpowers/brainstorm/56023-1779052031/content/*.html`

---

## 17. Next Step

Invoke `superpowers:writing-plans` to generate per-milestone implementation plans:
- `docs/superpowers/milestones/M0.md` → first.
- Plans link back to this spec.
- `frontend-todo.txt` initialized from M0 + M1 tasks.

Each subsequent session can be told: "Open M{N}.md and execute" — that's the user's ask for incremental hand-off-friendly milestones.
