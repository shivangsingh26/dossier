"""
dashboard.py — Dossier job tracker portal.

Two-panel layout: scrollable job cards (left) + sticky detail view (right).
Cards replace the spreadsheet data editor for a modern SaaS feel.

Phase B — modular, session-cached, no blocking I/O in render loop.

Run:   streamlit run dashboard.py
Share: ngrok http 8501  →  HTTPS URL via WhatsApp
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# ─── Constants ────────────────────────────────────────────────────────────────

DATA_ROOT    = Path("data")
PROFILE_ROOT = Path("profile")
AUTH_FILE    = PROFILE_ROOT / "auth.json"

STATUS_OPTIONS = ["Not Reviewed", "Interested", "Applied", "Skipped", "Rejected"]

STATUS_META = {
    "Not Reviewed": {"icon": "🔵", "color": "#6b7280"},
    "Interested":   {"icon": "⭐", "color": "#3b82f6"},
    "Applied":      {"icon": "✅", "color": "#22c55e"},
    "Skipped":      {"icon": "⏭️",  "color": "#f59e0b"},
    "Rejected":     {"icon": "❌", "color": "#ef4444"},
}

TAB_FILTERS = {
    "All":           None,
    "⭐ Interested":  "Interested",
    "✅ Applied":     "Applied",
    "🔵 New":         "Not Reviewed",
    "⏭️ Skipped":     "Skipped",
    "❌ Rejected":    "Rejected",
}

RELEVANCY_COLORS = {
    "STRONG": ("#15803d", "#dcfce7"),
    "GOOD":   ("#1d4ed8", "#dbeafe"),
    "FAIR":   ("#b45309", "#fef3c7"),
    "WEAK":   ("#6b7280", "#f3f4f6"),
}

MAX_CARDS = 40  # cap per tab to keep render fast


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _db(user: str) -> sqlite3.Connection:
    """Open user dossier.db with Row factory."""
    conn = sqlite3.connect(str(DATA_ROOT / user / "dossier.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_status_table(user: str) -> None:
    """Create job_status table if not present."""
    with _db(user) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS job_status (
                job_id     TEXT PRIMARY KEY,
                status     TEXT NOT NULL DEFAULT 'Not Reviewed',
                notes      TEXT DEFAULT '',
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()


def fetch_jobs(user: str, min_score: int) -> pd.DataFrame:
    """Load all scored jobs with user-edited status. Sorted score desc."""
    _ensure_status_table(user)
    with _db(user) as conn:
        rows = conn.execute("""
            SELECT
                j.job_id,
                j.company,
                j.title,
                j.score,
                j.relevancy,
                j.source,
                j.url,
                substr(j.scored_at, 1, 10)         AS found_date,
                COALESCE(s.status, 'Not Reviewed')  AS status,
                COALESCE(s.notes,  '')              AS notes
            FROM seen_jobs j
            LEFT JOIN job_status s ON j.job_id = s.job_id
            WHERE j.score >= ?
            ORDER BY j.score DESC, j.scored_at DESC
        """, (min_score,)).fetchall()
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame([dict(r) for r in rows])
        .drop_duplicates(subset=["job_id"], keep="first")
        .reset_index(drop=True)
    )


def upsert_status(user: str, job_id: str, status: str, notes: str = "") -> None:
    """Persist a single job status change."""
    with _db(user) as conn:
        conn.execute("""
            INSERT INTO job_status (job_id, status, notes, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status     = excluded.status,
                notes      = excluded.notes,
                updated_at = excluded.updated_at
        """, (job_id, status, notes, datetime.now(timezone.utc).isoformat()))
        conn.commit()


# ─── Artifact helpers ─────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def get_scorecard(user: str, job_id: str) -> dict | None:
    return _read_json(DATA_ROOT / user / "artifacts" / job_id / "score_card.json")


def get_gap(user: str, job_id: str) -> dict | None:
    return _read_json(DATA_ROOT / user / "artifacts" / job_id / "gap.json")


def get_jd(user: str, job_id: str) -> str:
    """Load full job description text."""
    path = DATA_ROOT / user / "artifacts" / job_id / "jd.txt"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def get_profile(user: str) -> dict | None:
    for p in [PROFILE_ROOT / user / "profile.json", PROFILE_ROOT / "profile.json"]:
        if p.exists():
            return json.loads(p.read_text())
    return None


def get_users() -> list[str]:
    if not DATA_ROOT.exists():
        return []
    return sorted(
        d.name for d in DATA_ROOT.iterdir()
        if d.is_dir() and (d / "dossier.db").exists()
    )


# ─── Auth helpers ─────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def load_auth() -> dict:
    """Return {user: hashed_password} from profile/auth.json."""
    if not AUTH_FILE.exists():
        return {}
    return json.loads(AUTH_FILE.read_text(encoding="utf-8"))


def verify(user: str, password: str) -> bool:
    auth = load_auth()
    return auth.get(user) == _hash(password)


def show_login() -> None:
    """Full-page login. Blocks until authenticated."""
    st.markdown("""
    <style>
    [data-testid="stSidebar"] { display: none !important; }
    .block-container { max-width: 420px !important; margin: 0 auto !important; }
    </style>
    <div style="text-align:center;padding:52px 0 28px">
        <div style="font-size:44px;margin-bottom:10px">🎯</div>
        <div style="font-size:26px;font-weight:800;color:#0f172a;letter-spacing:-0.8px">Dossier</div>
        <div style="font-size:13px;color:#94a3b8;margin-top:4px;font-weight:500">Job Intelligence Portal</div>
    </div>
    """, unsafe_allow_html=True)

    auth = load_auth()
    if not auth:
        st.error(
            "No passwords configured yet.\n\n"
            "Set one up:  `python scripts/set_password.py --user <name> --password <pass>`"
        )
        st.stop()

    with st.container(border=True):
        st.markdown(
            '<div style="font-size:15px;font-weight:700;color:#0f172a;margin-bottom:12px">Sign in to continue</div>',
            unsafe_allow_html=True,
        )
        with st.form("login_form", clear_on_submit=False):
            username = st.selectbox("Username", sorted(auth.keys()), label_visibility="collapsed")
            password = st.text_input("Password", type="password", placeholder="Password ···", label_visibility="collapsed")
            if st.form_submit_button("Continue →", use_container_width=True, type="primary"):
                if verify(username, password):
                    st.session_state.authenticated_user = username
                    st.rerun()
                else:
                    st.error("Incorrect password — try again.")


# ─── CSS ──────────────────────────────────────────────────────────────────────

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

/* ── Base reset — force light mode regardless of OS preference ── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
    -webkit-font-smoothing: antialiased;
    color-scheme: light !important;
}
html { background: #f8fafc !important; }
body { background: #f8fafc !important; color: #0f172a !important; }
#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding-top: 1.25rem !important;
    padding-bottom: 2rem !important;
    max-width: 1640px !important;
    background: transparent !important;
}
/* Force all text dark on light bg */
[data-testid="stAppViewContainer"] { background: #f8fafc !important; }
[data-testid="stMain"] { background: #f8fafc !important; }
[data-testid="stMarkdownContainer"] p { color: #374151 !important; }
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 { color: #0f172a !important; }

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: #0f172a !important;
    border-right: 1px solid rgba(255,255,255,0.05) !important;
}
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #cbd5e1 !important; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] code { color: #94a3b8 !important; background: #1e293b !important; }
[data-testid="stSidebar"] .stSelectbox > div > div {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] .stMultiSelect > div > div {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,0.07) !important; }
[data-testid="stSidebar"] .stButton > button {
    background: #1e293b !important;
    color: #cbd5e1 !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    transition: all 0.15s ease !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #334155 !important;
    border-color: #6366f1 !important;
    color: white !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 2px;
    background: #f1f5f9;
    border-radius: 10px;
    padding: 3px;
    border-bottom: none !important;
    box-shadow: inset 0 1px 2px rgba(0,0,0,0.04);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 7px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    padding: 5px 13px !important;
    color: #64748b !important;
    border: none !important;
    background: transparent !important;
}
.stTabs [aria-selected="true"] {
    background: white !important;
    color: #1e293b !important;
    font-weight: 600 !important;
    box-shadow: 0 1px 4px rgba(0,0,0,0.1) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {
    background: transparent !important;
    display: none !important;
}

/* ── Buttons ── */
.stButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    padding: 5px 10px !important;
    transition: all 0.12s ease !important;
    line-height: 1.4 !important;
}
.stButton > button[kind="primary"] {
    background: #6366f1 !important;
    border-color: #6366f1 !important;
    color: white !important;
}
.stButton > button[kind="primary"]:hover {
    background: #4f46e5 !important;
    border-color: #4f46e5 !important;
    box-shadow: 0 4px 12px rgba(99,102,241,0.35) !important;
    transform: translateY(-1px) !important;
}
.stButton > button[kind="secondary"] {
    background: white !important;
    border: 1.5px solid #e2e8f0 !important;
    color: #475569 !important;
}
.stButton > button[kind="secondary"]:hover {
    border-color: #a5b4fc !important;
    color: #6366f1 !important;
    background: #fafbff !important;
    transform: translateY(-1px) !important;
}
.stButton > button:focus { box-shadow: none !important; outline: none !important; }

/* ── Text input ── */
.stTextInput > div > div > input {
    border-radius: 9px !important;
    border: 1.5px solid #e2e8f0 !important;
    padding: 9px 13px !important;
    font-size: 14px !important;
    background: #fafafa !important;
    color: #0f172a !important;
    transition: all 0.12s ease !important;
    font-family: 'Inter', sans-serif !important;
}
.stTextInput > div > div > input::placeholder { color: #94a3b8 !important; }
.stTextInput > div > div > input:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.08) !important;
    background: white !important;
}

/* ── Textarea ── */
.stTextArea > div > div > textarea {
    border-radius: 8px !important;
    border: 1.5px solid #e2e8f0 !important;
    font-size: 13px !important;
    line-height: 1.6 !important;
    color: #1e293b !important;
    font-family: 'Inter', sans-serif !important;
    transition: border-color 0.12s ease !important;
}
.stTextArea > div > div > textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.08) !important;
}

/* ── Job card shell (via stVerticalBlockBorderWrapper) ── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 12px !important;
    border: 1.5px solid #e2e8f0 !important;
    padding: 0 !important;
    margin-bottom: 6px !important;
    transition: border-color 0.12s ease, box-shadow 0.12s ease !important;
    background: #ffffff !important;
    overflow: hidden !important;
    color-scheme: light !important;
}
[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: #a5b4fc !important;
    box-shadow: 0 2px 14px rgba(99,102,241,0.09) !important;
}

/* ── Ensure inner text stays dark ── */
[data-testid="stVerticalBlockBorderWrapper"] p,
[data-testid="stVerticalBlockBorderWrapper"] span,
[data-testid="stVerticalBlockBorderWrapper"] div { color: inherit; }

/* ── KPI cards ── */
.kpi-card {
    background: white;
    border: 1.5px solid #e2e8f0;
    border-radius: 14px;
    padding: 16px 18px 14px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    height: 100%;
    transition: box-shadow 0.12s ease, transform 0.12s ease;
}
.kpi-card:hover {
    box-shadow: 0 6px 20px rgba(0,0,0,0.08);
    transform: translateY(-1px);
}

/* ── Detail panel ── */
.detail-panel {
    background: white;
    border: 1.5px solid #e2e8f0;
    border-radius: 14px;
    padding: 20px 22px;
    position: sticky;
    top: 16px;
    max-height: calc(100vh - 60px);
    overflow-y: auto;
    scrollbar-width: thin;
    scrollbar-color: #e2e8f0 transparent;
}
.detail-panel::-webkit-scrollbar { width: 4px; }
.detail-panel::-webkit-scrollbar-track { background: transparent; }
.detail-panel::-webkit-scrollbar-thumb { background: #e2e8f0; border-radius: 4px; }

/* ── Skill tags ── */
.skill-tag {
    display: inline-block;
    padding: 3px 9px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 500;
    margin: 2px 2px 2px 0;
}

/* ── Section label ── */
.section-label {
    font-size: 11px;
    font-weight: 700;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin: 14px 0 6px;
}

/* ── Reason card ── */
.reason-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 13px;
    color: #1e293b;
    line-height: 1.65;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1.5px solid #e2e8f0 !important;
    border-radius: 10px !important;
    overflow: hidden !important;
    background: white !important;
}

/* ── Link button ── */
[data-testid="stLinkButton"] > a {
    border-radius: 8px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    transition: all 0.12s ease !important;
}

/* ── Toast ── */
[data-testid="stToast"] {
    border-radius: 10px !important;
    font-weight: 500 !important;
    font-size: 13px !important;
    box-shadow: 0 4px 16px rgba(0,0,0,0.12) !important;
}

/* ── Selectbox ── */
.stSelectbox > div > div {
    border-radius: 8px !important;
    font-size: 13px !important;
    transition: border-color 0.12s !important;
}

/* ── Alert/info ── */
[data-testid="stAlert"] {
    border-radius: 10px !important;
    font-size: 13px !important;
}

/* ── Progress bar ── */
.prog-track {
    background: #f1f5f9;
    border-radius: 8px;
    height: 5px;
    overflow: hidden;
    margin: 14px 0 3px;
}
.prog-fill {
    height: 100%;
    border-radius: 8px;
    background: linear-gradient(90deg, #6366f1, #a78bfa);
    transition: width 0.4s ease;
}
</style>
"""


# ─── HTML component functions ──────────────────────────────────────────────────

def kpi_card_html(icon: str, label: str, value: int | str, color: str, sub: str = "") -> str:
    sub_html = f'<div style="font-size:11px;color:#94a3b8;margin-top:3px;font-weight:400">{sub}</div>' if sub else ""
    return f"""
    <div class="kpi-card" style="border-top:3px solid {color}">
        <div style="font-size:20px;margin-bottom:6px">{icon}</div>
        <div style="font-size:26px;font-weight:800;color:{color};line-height:1;letter-spacing:-0.5px">{value}</div>
        <div style="font-size:11px;color:#64748b;font-weight:600;margin-top:5px;text-transform:uppercase;letter-spacing:0.5px">{label}</div>
        {sub_html}
    </div>"""


def score_badge_html(score: int) -> str:
    if score >= 9:   c, bg = "#15803d", "#dcfce7"
    elif score >= 7: c, bg = "#1d4ed8", "#dbeafe"
    elif score >= 5: c, bg = "#b45309", "#fef3c7"
    else:            c, bg = "#b91c1c", "#fee2e2"
    return (
        f'<span style="background:{bg};color:{c};padding:3px 10px;'
        f'border-radius:20px;font-size:12px;font-weight:700">{score}/10</span>'
    )


def status_pill_html(status: str) -> str:
    m = STATUS_META.get(status, STATUS_META["Not Reviewed"])
    return (
        f'<span style="background:{m["color"]}18;color:{m["color"]};padding:3px 9px;'
        f'border-radius:20px;font-size:12px;font-weight:600;border:1px solid {m["color"]}40">'
        f'{m["icon"]} {status}</span>'
    )


def skill_tag_html(skill: str, color: str = "#6366f1", bg: str = "#eef2ff") -> str:
    return (
        f'<span class="skill-tag" style="background:{bg};color:{color}">{skill}</span>'
    )


def relevancy_tag_html(relevancy: str) -> str:
    c, bg = RELEVANCY_COLORS.get((relevancy or "").upper(), ("#6b7280", "#f3f4f6"))
    return (
        f'<span style="background:{bg};color:{c};padding:2px 7px;border-radius:5px;'
        f'font-size:10px;font-weight:700;letter-spacing:0.3px">{relevancy}</span>'
    )


def section_header(title: str) -> None:
    st.markdown(f'<div class="section-label">{title}</div>', unsafe_allow_html=True)


# ─── Card renderer ─────────────────────────────────────────────────────────────

def render_job_card(row: pd.Series, user: str, cache_key: str, is_selected: bool, tab_key: str = "") -> None:
    """Render a single job as a card with inline quick-action buttons."""
    score  = int(row["score"])
    status = row["status"]
    job_id = row["job_id"]
    m      = STATUS_META.get(status, STATUS_META["Not Reviewed"])

    if score >= 9:   sc, sbg = "#15803d", "#dcfce7"
    elif score >= 7: sc, sbg = "#1d4ed8", "#dbeafe"
    elif score >= 5: sc, sbg = "#b45309", "#fef3c7"
    else:            sc, sbg = "#b91c1c", "#fee2e2"

    relevancy = str(row.get("relevancy", "") or "")
    rel_html  = relevancy_tag_html(relevancy) if relevancy else ""

    # Left border accent for selected card
    accent = "border-left:3px solid #6366f1 !important;" if is_selected else ""

    with st.container(border=True):
        # Card body — non-interactive, pure HTML
        st.markdown(f"""
        <div style="padding:4px 6px 6px;{accent}">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
                <div style="flex:1;min-width:0;overflow:hidden">
                    <div style="font-size:15px;font-weight:700;color:#0f172a;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                        letter-spacing:-0.2px">{row['company']}</div>
                    <div style="font-size:13px;color:#475569;margin-top:2px;
                        white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{row['title']}</div>
                </div>
                <div style="display:flex;flex-direction:column;align-items:flex-end;
                    gap:4px;flex-shrink:0">
                    <span style="background:{sbg};color:{sc};padding:3px 9px;
                        border-radius:20px;font-size:11px;font-weight:700">{score}/10</span>
                    <span style="background:{m['color']}18;color:{m['color']};
                        border:1px solid {m['color']}40;padding:2px 7px;
                        border-radius:20px;font-size:10px;font-weight:600">{m['icon']} {status}</span>
                </div>
            </div>
            <div style="margin-top:8px;font-size:11px;color:#94a3b8;
                display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                {rel_html}
                {'<span style="color:#e2e8f0">·</span>' if rel_html else ''}
                <span style="font-weight:500;color:#64748b">{row['source']}</span>
                <span style="color:#e2e8f0">·</span>
                <span>{row['found_date']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Quick-action row: 5 status buttons + Details
        b1, b2, b3, b4, b5, bdet = st.columns([1, 1, 1, 1, 1, 1.6])
        for (s_opt, icon), col in zip(
            [("Interested", "⭐"), ("Applied", "✅"),
             ("Skipped", "⏭️"), ("Not Reviewed", "🔵"), ("Rejected", "❌")],
            [b1, b2, b3, b4, b5],
        ):
            with col:
                is_cur = status == s_opt
                if st.button(
                    icon,
                    key=f"q_{tab_key}_{job_id}_{s_opt}",
                    use_container_width=True,
                    type="primary" if is_cur else "secondary",
                    help=s_opt,
                ):
                    upsert_status(user, job_id, s_opt)
                    mask = st.session_state[cache_key]["job_id"] == job_id
                    st.session_state[cache_key].loc[mask, "status"] = s_opt
                    st.toast(f"{icon} Marked as {s_opt}", icon=icon)
                    st.rerun()
        with bdet:
            if st.button("Details →", key=f"det_{tab_key}_{job_id}", use_container_width=True):
                st.session_state.detail_job_id = job_id
                st.rerun()


# ─── Detail panel renderer ─────────────────────────────────────────────────────

def render_detail_panel(df_view: pd.DataFrame, user: str, cache_key: str) -> None:
    """Render the sticky right-side detail view for the selected job."""
    job_id = st.session_state.get("detail_job_id")

    if not job_id or df_view[df_view["job_id"] == job_id].empty:
        st.markdown("""
        <div class="detail-panel">
            <div style="text-align:center;padding:60px 0;color:#94a3b8">
                <div style="font-size:32px;margin-bottom:10px">←</div>
                <div style="font-size:14px;font-weight:500">Select a job to see details</div>
                <div style="font-size:12px;margin-top:4px">Click "Details →" on any card</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        return

    row       = df_view[df_view["job_id"] == job_id].iloc[0]
    scorecard = get_scorecard(user, job_id)
    gap       = get_gap(user, job_id)
    jd_text   = get_jd(user, job_id)

    score   = scorecard.get("score", row["score"]) if scorecard else row["score"]
    urgency = scorecard.get("urgency", "") if scorecard else ""
    url     = scorecard.get("url", row["url"]) if scorecard else row["url"]

    # ── Header ──
    st.markdown(f"""
    <div style="margin-bottom:14px">
        <div style="font-size:18px;font-weight:800;color:#0f172a;letter-spacing:-0.4px;line-height:1.2">{row['company']}</div>
        <div style="font-size:13px;color:#475569;margin-top:3px;font-weight:400">{row['title']}</div>
        <div style="margin-top:10px;display:flex;gap:6px;align-items:center;flex-wrap:wrap">
            {score_badge_html(int(score))}
            {status_pill_html(row['status'])}
            {('<span style="background:#fef2f2;color:#ef4444;padding:3px 9px;border-radius:20px;font-size:11px;font-weight:700">🔥 ' + urgency + '</span>') if urgency else ''}
        </div>
        {('<div style="margin-top:10px"><a href="' + url + '" target="_blank" style="font-size:13px;color:#6366f1;font-weight:600;text-decoration:none">View Job ↗</a></div>') if url else ''}
    </div>
    <hr style="border:none;border-top:1px solid #f1f5f9;margin:0 0 4px">
    """, unsafe_allow_html=True)

    # ── Quick status update ──
    section_header("Update status")
    btn_cols = st.columns(len(STATUS_OPTIONS))
    for s_opt, col in zip(STATUS_OPTIONS, btn_cols):
        m = STATUS_META[s_opt]
        is_cur = row["status"] == s_opt
        with col:
            if st.button(
                m["icon"],
                key=f"panel_q_{job_id}_{s_opt}",
                type="primary" if is_cur else "secondary",
                use_container_width=True,
                help=s_opt,
            ):
                upsert_status(user, job_id, s_opt)
                mask = st.session_state[cache_key]["job_id"] == job_id
                st.session_state[cache_key].loc[mask, "status"] = s_opt
                st.toast(f"{m['icon']} {s_opt}", icon=m["icon"])
                st.rerun()

    # ── Why this match ──
    if scorecard and scorecard.get("reason"):
        section_header("Why this match")
        st.markdown(
            f'<div class="reason-card">{scorecard["reason"]}</div>',
            unsafe_allow_html=True,
        )

    # ── Skills you have ──
    req_miss  = scorecard.get("required_skills_missing",  []) if scorecard else []
    pref_miss = scorecard.get("preferred_skills_missing", []) if scorecard else []

    if gap:
        has_req  = gap.get("candidate_has_required",  [])
        miss_req = gap.get("candidate_missing_required", [])
        has_pref = gap.get("candidate_has_preferred",  [])

        if has_req:
            section_header("✅ You already have")
            st.markdown(
                "".join(skill_tag_html(s, "#15803d", "#dcfce7") for s in has_req),
                unsafe_allow_html=True,
            )
        if miss_req:
            section_header("❌ Gaps to close")
            st.markdown(
                "".join(skill_tag_html(s, "#b91c1c", "#fee2e2") for s in miss_req),
                unsafe_allow_html=True,
            )
        if has_pref:
            section_header("⭐ Bonus skills you have")
            st.markdown(
                "".join(skill_tag_html(s, "#6366f1", "#eef2ff") for s in has_pref),
                unsafe_allow_html=True,
            )
    elif req_miss or pref_miss:
        section_header("Skills to build")
        html = "".join(skill_tag_html(s, "#b91c1c", "#fee2e2") for s in req_miss)
        html += "".join(skill_tag_html(s, "#b45309", "#fef3c7") for s in pref_miss[:5])
        st.markdown(html, unsafe_allow_html=True)

    # ── Notes ──
    section_header("Your notes")
    current_notes = str(row["notes"]) if row["notes"] else ""
    new_notes = st.text_area(
        "Notes",
        value=current_notes,
        placeholder="Interview notes, referral contacts, follow-up dates…",
        height=90,
        label_visibility="collapsed",
        key=f"notes_{job_id}",
    )
    if new_notes != current_notes:
        upsert_status(user, job_id, row["status"], new_notes)
        mask = st.session_state[cache_key]["job_id"] == job_id
        st.session_state[cache_key].loc[mask, "notes"] = new_notes
        st.toast("Notes saved ✓", icon="💾")

    # ── JD preview ──
    if jd_text:
        st.markdown('<div style="height:6px"></div>', unsafe_allow_html=True)
        with st.expander("📄 Full job description"):
            st.markdown(
                f'<div style="font-size:12px;color:#475569;line-height:1.75;white-space:pre-wrap">{jd_text}</div>',
                unsafe_allow_html=True,
            )


# ─── Page setup ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Dossier — Job Tracker",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ─── Auth gate ────────────────────────────────────────────────────────────────

if "authenticated_user" not in st.session_state:
    show_login()
    st.stop()

user    = st.session_state.authenticated_user
profile = get_profile(user)

if not (DATA_ROOT / user / "dossier.db").exists():
    st.warning(
        f"No pipeline data for **{user}** yet.\n\n"
        f"Run: `python run_dossier.py --user {user}`"
    )
    if st.button("Sign out"):
        del st.session_state.authenticated_user
        st.rerun()
    st.stop()


# ─── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown(
        '<div style="font-size:22px;font-weight:800;letter-spacing:-0.6px;padding:4px 0 2px">'
        '🎯 Dossier</div>'
        '<div style="font-size:11px;color:#64748b;margin-bottom:10px;font-weight:500">Job Intelligence Portal</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<hr style='border-color:rgba(255,255,255,0.07);margin:4px 0 12px'>", unsafe_allow_html=True)

    if profile:
        identity = profile.get("identity", {})
        initials = "".join(w[0].upper() for w in identity.get("name", user).split()[:2])
        st.markdown(
            f'<div style="background:#1e293b;border-radius:10px;padding:12px 14px;margin:6px 0 12px">'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<div style="width:34px;height:34px;border-radius:50%;background:linear-gradient(135deg,#6366f1,#8b5cf6);'
            f'display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;color:white;flex-shrink:0">{initials}</div>'
            f'<div>'
            f'<div style="font-size:14px;font-weight:700;color:#f1f5f9">{identity.get("name", user)}</div>'
            f'<div style="font-size:11px;color:#64748b;margin-top:1px">{identity.get("current_role","")}</div>'
            f'<div style="font-size:11px;color:#64748b">{identity.get("current_company","")} · {identity.get("location","")}</div>'
            f'</div></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div style="font-size:11px;font-weight:600;color:#475569;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px">Filters</div>', unsafe_allow_html=True)

    min_score = st.slider("Minimum score", 1, 10, 5, label_visibility="visible")

    _df_opts = fetch_jobs(user, 1)
    all_sources = sorted(_df_opts["source"].unique()) if not _df_opts.empty else []
    if all_sources:
        source_filter = st.multiselect("Sources", all_sources, default=all_sources)
    else:
        source_filter = []

    st.markdown("<hr style='border-color:rgba(255,255,255,0.07);margin:12px 0'>", unsafe_allow_html=True)

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if st.button("🔄 Refresh", use_container_width=True):
            for k in list(st.session_state.keys()):
                if k.startswith("df_"):
                    del st.session_state[k]
            st.rerun()
    with col_r2:
        if st.button("Sign out", use_container_width=True):
            del st.session_state.authenticated_user
            st.rerun()

    st.markdown("<hr style='border-color:rgba(255,255,255,0.07);margin:12px 0'>", unsafe_allow_html=True)
    st.markdown('<div style="font-size:11px;font-weight:600;color:#475569;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px">Share portal</div>', unsafe_allow_html=True)
    st.code("ngrok http 8501", language="bash")
    st.caption("Run above → copy HTTPS URL → send via WhatsApp 💬")


# ─── Load data ────────────────────────────────────────────────────────────────

cache_key = f"df_{user}_{min_score}"
if cache_key not in st.session_state:
    with st.spinner("Loading jobs…"):
        st.session_state[cache_key] = fetch_jobs(user, min_score)

df_all = st.session_state[cache_key].copy()

if df_all.empty:
    st.warning(f"⚠️ No jobs for **{user}**. Run: `python run_dossier.py --user {user}`")
    st.stop()

if source_filter:
    df_all = df_all[df_all["source"].isin(source_filter)].reset_index(drop=True)


# ─── Header ───────────────────────────────────────────────────────────────────

name         = profile["identity"]["name"] if profile else user.capitalize()
target_roles = ", ".join(profile["target"]["roles"][:3]) if profile else ""

st.markdown(
    f'<div style="margin-bottom:18px">'
    f'<h1 style="font-size:26px;font-weight:800;color:#0f172a;margin:0;letter-spacing:-0.6px">'
    f'Welcome back, {name.split()[0]} 👋</h1>'
    f'<div style="color:#64748b;font-size:13px;margin-top:4px;font-weight:400">'
    f'Targeting {target_roles} · Scores ≥ {min_score}/10</div>'
    f'</div>',
    unsafe_allow_html=True,
)


# ─── KPI row ──────────────────────────────────────────────────────────────────

total        = len(df_all)
high_score   = len(df_all[df_all["score"] >= 8])
not_reviewed = len(df_all[df_all["status"] == "Not Reviewed"])
interested   = len(df_all[df_all["status"] == "Interested"])
applied      = len(df_all[df_all["status"] == "Applied"])
review_pct   = int(100 * (total - not_reviewed) / total) if total else 0

c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.markdown(kpi_card_html("📋", "Total Jobs",  total,        "#6b7280"), unsafe_allow_html=True)
with c2: st.markdown(kpi_card_html("🏆", "High Match",  high_score,   "#22c55e", "Score ≥ 8"), unsafe_allow_html=True)
with c3: st.markdown(kpi_card_html("⭐", "Interested",  interested,   "#3b82f6"), unsafe_allow_html=True)
with c4: st.markdown(kpi_card_html("✅", "Applied",     applied,      "#8b5cf6"), unsafe_allow_html=True)
with c5: st.markdown(kpi_card_html("🔵", "To Review",   not_reviewed, "#f59e0b", f"{review_pct}% done"), unsafe_allow_html=True)

if total:
    st.markdown(
        f'<div class="prog-track"><div class="prog-fill" style="width:{review_pct}%"></div></div>'
        f'<div style="font-size:11px;color:#94a3b8;text-align:right;margin-bottom:4px">{review_pct}% reviewed</div>',
        unsafe_allow_html=True,
    )

st.markdown('<div style="height:10px"></div>', unsafe_allow_html=True)


# ─── Search ───────────────────────────────────────────────────────────────────

search_col, _ = st.columns([2, 3])
with search_col:
    search_query = st.text_input(
        "Search",
        placeholder="🔍  Search company or role…",
        label_visibility="collapsed",
    )

df_view = df_all.copy()
if search_query:
    mask = (
        df_view["company"].str.contains(search_query, case=False, na=False) |
        df_view["title"].str.contains(search_query, case=False, na=False)
    )
    df_view = df_view[mask].reset_index(drop=True)

# Default selected job — first in view (or preserve existing if still visible)
existing = st.session_state.get("detail_job_id")
if not df_view.empty:
    visible_ids = set(df_view["job_id"].tolist())
    if existing not in visible_ids:
        st.session_state.detail_job_id = df_view.iloc[0]["job_id"]
else:
    st.session_state.detail_job_id = None


# ─── Two-panel layout ─────────────────────────────────────────────────────────

list_col, detail_col = st.columns([11, 9], gap="large")

with list_col:
    tab_labels = list(TAB_FILTERS.keys())
    tabs       = st.tabs(tab_labels)

    for tab_label, tab_obj in zip(tab_labels, tabs):
        with tab_obj:
            status_val = TAB_FILTERS[tab_label]
            df_tab = (
                df_view.copy()
                if status_val is None
                else df_view[df_view["status"] == status_val].copy()
            )
            df_tab = df_tab.reset_index(drop=True)

            if df_tab.empty:
                st.markdown(
                    '<div style="text-align:center;padding:48px 0;color:#94a3b8">'
                    '<div style="font-size:32px;margin-bottom:8px">🎉</div>'
                    '<div style="font-size:14px;font-weight:500">Nothing here</div>'
                    '<div style="font-size:12px;margin-top:4px">Try a different filter or lower the score threshold</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )
                continue

            n_total = len(df_tab)
            df_show = df_tab.head(MAX_CARDS)
            st.markdown(
                f'<div style="font-size:12px;color:#94a3b8;margin:6px 0 10px;font-weight:500">'
                f'{"Showing " + str(len(df_show)) + " of " if n_total > MAX_CARDS else ""}'
                f'<b style="color:#475569">{n_total}</b> job{"s" if n_total != 1 else ""}'
                f' — click a card\'s icon to update status</div>',
                unsafe_allow_html=True,
            )

            for _, row in df_show.iterrows():
                is_selected = row["job_id"] == st.session_state.get("detail_job_id")
                render_job_card(row, user, cache_key, is_selected, tab_key=tab_label)

            if n_total > MAX_CARDS:
                st.info(f"Showing top {MAX_CARDS} of {n_total} jobs. Raise the score filter to narrow down.")

with detail_col:
    render_detail_panel(df_view, user, cache_key)
