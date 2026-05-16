"""
dashboard.py — Dossier job tracker portal.

What users see: their scored jobs, match reasons, skill gaps, one-tap status updates.
What this is NOT: a pipeline monitor. All pipeline internals are hidden.

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
    "All":          None,
    "⭐ Interested": "Interested",
    "✅ Applied":    "Applied",
    "🔵 Not Reviewed": "Not Reviewed",
    "⏭️ Skipped":    "Skipped",
}


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
    return pd.DataFrame([dict(r) for r in rows]).reset_index(drop=True)


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


def bulk_save(user: str, rows: pd.DataFrame) -> None:
    """Persist multiple status changes at once. rows needs job_id, status, notes."""
    now = datetime.now(timezone.utc).isoformat()
    with _db(user) as conn:
        for _, r in rows.iterrows():
            conn.execute("""
                INSERT INTO job_status (job_id, status, notes, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status = excluded.status, notes = excluded.notes,
                    updated_at = excluded.updated_at
            """, (r["job_id"], r["status"], r["notes"], now))
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
    """Return {user: hashed_password} from profile/auth.json. Empty dict if missing."""
    if not AUTH_FILE.exists():
        return {}
    return json.loads(AUTH_FILE.read_text(encoding="utf-8"))


def verify(user: str, password: str) -> bool:
    """Return True if password matches the stored hash for user."""
    auth = load_auth()
    return auth.get(user) == _hash(password)


def show_login() -> None:
    """Render the full-page login form. Blocks until authenticated."""
    st.markdown("""
    <style>
    .login-wrap {
        display: flex; justify-content: center; align-items: center;
        min-height: 70vh;
    }
    .login-card {
        background: white; border: 1px solid #e2e8f0; border-radius: 18px;
        padding: 40px 44px; max-width: 400px; width: 100%;
        box-shadow: 0 8px 32px rgba(0,0,0,0.08);
        text-align: center;
    }
    </style>
    <div class="login-wrap"><div class="login-card">
    <div style="font-size:40px;margin-bottom:8px">🎯</div>
    <div style="font-size:22px;font-weight:800;color:#0f172a;letter-spacing:-0.5px">Dossier</div>
    <div style="font-size:13px;color:#94a3b8;margin-bottom:28px">Job Intelligence Portal</div>
    </div></div>
    """, unsafe_allow_html=True)

    auth = load_auth()
    if not auth:
        st.error(
            "No passwords configured yet.\n\n"
            "Set one up:  `python scripts/set_password.py --user <name> --password <pass>`"
        )
        st.stop()

    _, col_c, _ = st.columns([1, 2, 1])
    with col_c:
        with st.form("login_form", clear_on_submit=False):
            st.markdown(
                '<div style="font-size:15px;font-weight:600;color:#1e293b;margin-bottom:4px">Sign in</div>',
                unsafe_allow_html=True,
            )
            username = st.selectbox("Username", sorted(auth.keys()), label_visibility="collapsed")
            password = st.text_input("Password", type="password", placeholder="Password", label_visibility="collapsed")
            submitted = st.form_submit_button("Sign in →", use_container_width=True, type="primary")

            if submitted:
                if verify(username, password):
                    st.session_state.authenticated_user = username
                    st.rerun()
                else:
                    st.error("Incorrect password. Try again.")


# ─── CSS ──────────────────────────────────────────────────────────────────────

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding-top: 1.5rem !important;
    padding-bottom: 2rem !important;
    max-width: 1600px !important;
}

/* ── Sidebar ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0f172a 0%, #1e1b4b 100%) !important;
    border-right: 1px solid #1e293b;
}
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
[data-testid="stSidebar"] .stSelectbox > div > div {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    border-radius: 8px !important;
}
[data-testid="stSidebar"] hr { border-color: #1e293b !important; }
[data-testid="stSidebar"] .stButton > button {
    background: #3730a3 !important;
    color: white !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
}
[data-testid="stSidebar"] .stButton > button:hover {
    background: #4338ca !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(99,102,241,0.4) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: #f1f5f9;
    border-radius: 12px;
    padding: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px !important;
    font-weight: 500 !important;
    font-size: 14px !important;
    padding: 6px 16px !important;
    color: #64748b !important;
}
.stTabs [aria-selected="true"] {
    background: white !important;
    color: #1e293b !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12) !important;
}
.stTabs [data-baseweb="tab-highlight"] { background: transparent !important; }

/* ── Buttons ── */
.stButton > button {
    border-radius: 8px !important;
    font-weight: 500 !important;
    transition: all 0.15s ease !important;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.15) !important;
}

/* ── Data editor ── */
[data-testid="stDataEditor"] {
    border-radius: 12px !important;
    overflow: hidden;
    border: 1px solid #e2e8f0 !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    border: 1px solid #e2e8f0 !important;
    border-radius: 10px !important;
    overflow: hidden;
}

/* ── Text input / search ── */
.stTextInput > div > div > input {
    border-radius: 10px !important;
    border: 1.5px solid #e2e8f0 !important;
    padding: 10px 14px !important;
    font-size: 14px !important;
    transition: border-color 0.15s ease !important;
}
.stTextInput > div > div > input:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.1) !important;
}

/* ── Selectbox ── */
.stSelectbox > div > div {
    border-radius: 10px !important;
}

/* ── Toast ── */
[data-testid="stToast"] {
    border-radius: 10px !important;
    font-weight: 500 !important;
}
</style>
"""

# ─── Reusable HTML components ─────────────────────────────────────────────────

def kpi_card_html(icon: str, label: str, value: int | str, color: str, sub: str = "") -> str:
    return f"""
    <div style="
        background: white;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 18px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        border-top: 3px solid {color};
        height: 100%;
    ">
        <div style="font-size:22px; margin-bottom:6px">{icon}</div>
        <div style="font-size:28px; font-weight:800; color:{color}; line-height:1">{value}</div>
        <div style="font-size:12px; color:#64748b; font-weight:500; margin-top:4px; text-transform:uppercase; letter-spacing:0.5px">{label}</div>
        {"<div style='font-size:11px; color:#94a3b8; margin-top:2px'>" + sub + "</div>" if sub else ""}
    </div>"""


def score_badge_html(score: int) -> str:
    if score >= 9:   color, bg = "#15803d", "#dcfce7"
    elif score >= 7: color, bg = "#1d4ed8", "#dbeafe"
    elif score >= 5: color, bg = "#b45309", "#fef3c7"
    else:            color, bg = "#b91c1c", "#fee2e2"
    return (
        f'<span style="background:{bg};color:{color};padding:3px 10px;'
        f'border-radius:20px;font-size:12px;font-weight:700">{score}/10</span>'
    )


def status_pill_html(status: str) -> str:
    m = STATUS_META.get(status, STATUS_META["Not Reviewed"])
    return (
        f'<span style="background:{m["color"]}18;color:{m["color"]};padding:3px 10px;'
        f'border-radius:20px;font-size:12px;font-weight:600;border:1px solid {m["color"]}40">'
        f'{m["icon"]} {status}</span>'
    )


def skill_tag_html(skill: str, color: str = "#6366f1", bg: str = "#eef2ff") -> str:
    return (
        f'<span style="background:{bg};color:{color};padding:2px 8px;'
        f'border-radius:6px;font-size:12px;font-weight:500;margin:2px;display:inline-block">'
        f'{skill}</span>'
    )


def section_header(title: str) -> None:
    st.markdown(
        f'<div style="font-size:13px;font-weight:700;color:#64748b;'
        f'text-transform:uppercase;letter-spacing:0.8px;margin:8px 0 6px">{title}</div>',
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

# Safety check — user must have pipeline data
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
        '<div style="font-size:22px;font-weight:800;letter-spacing:-0.5px;padding:4px 0 2px">'
        '🎯 Dossier</div>'
        '<div style="font-size:11px;color:#94a3b8;margin-bottom:12px">Job Intelligence Portal</div>',
        unsafe_allow_html=True,
    )
    st.markdown("<hr style='border-color:#1e293b;margin:4px 0 12px'>", unsafe_allow_html=True)

    if profile:
        identity = profile.get("identity", {})
        st.markdown(
            f'<div style="background:#1e293b;border-radius:10px;padding:12px 14px;margin:8px 0">'
            f'<div style="font-size:15px;font-weight:700">{identity.get("name", user)}</div>'
            f'<div style="font-size:12px;color:#94a3b8;margin-top:2px">'
            f'{identity.get("current_role","")}</div>'
            f'<div style="font-size:12px;color:#94a3b8">'
            f'{identity.get("current_company","")} · {identity.get("location","")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown("<hr style='border-color:#1e293b;margin:12px 0'>", unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px">Filters</div>', unsafe_allow_html=True)

    min_score = st.slider("Minimum score", 1, 10, 5, label_visibility="visible")

    _df_opts = fetch_jobs(user, 1)
    all_sources = sorted(_df_opts["source"].unique()) if not _df_opts.empty else []
    if all_sources:
        source_filter = st.multiselect("Sources", all_sources, default=all_sources)
    else:
        source_filter = []

    st.markdown("<hr style='border-color:#1e293b;margin:12px 0'>", unsafe_allow_html=True)

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

    st.markdown("<hr style='border-color:#1e293b;margin:12px 0'>", unsafe_allow_html=True)
    st.markdown('<div style="font-size:12px;font-weight:600;color:#94a3b8;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px">Share this portal</div>', unsafe_allow_html=True)
    st.code("ngrok http 8501", language="bash")
    st.caption("Run above → copy HTTPS URL → send via WhatsApp 💬")


# ─── Load data ────────────────────────────────────────────────────────────────

cache_key = f"df_{user}_{min_score}"
if cache_key not in st.session_state:
    with st.spinner("Loading jobs…"):
        st.session_state[cache_key] = fetch_jobs(user, min_score)

df_all = st.session_state[cache_key].copy()

if df_all.empty:
    st.warning(
        f"⚠️ No jobs found for **{user}**. "
        f"Run: `python run_dossier.py --user {user}`"
    )
    st.stop()

# Source filter
if source_filter:
    df_all = df_all[df_all["source"].isin(source_filter)].reset_index(drop=True)


# ─── Header ───────────────────────────────────────────────────────────────────

name = profile["identity"]["name"] if profile else user.capitalize()
target_roles = ", ".join(profile["target"]["roles"][:3]) if profile else ""

st.markdown(
    f'<div style="margin-bottom:20px">'
    f'<h1 style="font-size:28px;font-weight:800;color:#0f172a;margin:0;letter-spacing:-0.5px">'
    f'Welcome back, {name.split()[0]} 👋</h1>'
    f'<div style="color:#64748b;font-size:14px;margin-top:4px">'
    f'Targeting: {target_roles} · Scores ≥ {min_score}/10</div>'
    f'</div>',
    unsafe_allow_html=True,
)


# ─── KPI row ──────────────────────────────────────────────────────────────────

total        = len(df_all)
high_score   = len(df_all[df_all["score"] >= 8])
not_reviewed = len(df_all[df_all["status"] == "Not Reviewed"])
interested   = len(df_all[df_all["status"] == "Interested"])
applied      = len(df_all[df_all["status"] == "Applied"])

review_pct = int(100 * (total - not_reviewed) / total) if total else 0

c1, c2, c3, c4, c5 = st.columns(5)
with c1: st.markdown(kpi_card_html("📋", "Total Jobs", total, "#6b7280"), unsafe_allow_html=True)
with c2: st.markdown(kpi_card_html("🏆", "High Match", high_score, "#22c55e", "Score ≥ 8"), unsafe_allow_html=True)
with c3: st.markdown(kpi_card_html("⭐", "Interested", interested, "#3b82f6"), unsafe_allow_html=True)
with c4: st.markdown(kpi_card_html("✅", "Applied", applied, "#8b5cf6"), unsafe_allow_html=True)
with c5: st.markdown(kpi_card_html("🔵", "To Review", not_reviewed, "#f59e0b", f"{review_pct}% done"), unsafe_allow_html=True)

# Review progress bar
if total:
    progress_html = f"""
    <div style="margin: 16px 0 4px; background:#f1f5f9; border-radius:8px; height:6px; overflow:hidden">
        <div style="width:{review_pct}%; background:linear-gradient(90deg,#6366f1,#8b5cf6);
        height:100%; border-radius:8px; transition:width 0.3s ease"></div>
    </div>
    <div style="font-size:11px; color:#94a3b8; text-align:right">{review_pct}% reviewed</div>
    """
    st.markdown(progress_html, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)


# ─── Search + Tabs ────────────────────────────────────────────────────────────

search_col, _ = st.columns([2, 3])
with search_col:
    search_query = st.text_input(
        "Search",
        placeholder="🔍  Search company or job title…",
        label_visibility="collapsed",
    )

# Apply search
df_view = df_all.copy()
if search_query:
    mask = (
        df_view["company"].str.contains(search_query, case=False, na=False) |
        df_view["title"].str.contains(search_query, case=False, na=False)
    )
    df_view = df_view[mask].reset_index(drop=True)

# Tab-based status filter
tab_labels = list(TAB_FILTERS.keys())
tabs = st.tabs(tab_labels)

for tab_label, tab_obj in zip(tab_labels, tabs):
    with tab_obj:
        status_val = TAB_FILTERS[tab_label]
        df_tab = df_view.copy() if status_val is None else df_view[df_view["status"] == status_val].copy()
        df_tab = df_tab.reset_index(drop=True)

        if df_tab.empty:
            st.markdown(
                '<div style="text-align:center;padding:40px;color:#94a3b8;">'
                '<div style="font-size:32px;margin-bottom:8px">🎉</div>'
                '<div style="font-size:14px">No jobs here</div></div>',
                unsafe_allow_html=True,
            )
            continue

        st.markdown(
            f'<div style="font-size:13px;color:#64748b;margin:8px 0 4px">'
            f'<b>{len(df_tab)}</b> jobs — edit Status and Notes inline, saves automatically</div>',
            unsafe_allow_html=True,
        )

        # job_id hidden via column_order
        edited = st.data_editor(
            df_tab[[
                "job_id", "company", "title", "score",
                "relevancy", "source", "found_date", "status", "notes", "url",
            ]],
            column_order=["company", "title", "score", "relevancy", "source", "found_date", "status", "notes", "url"],
            column_config={
                "company":    st.column_config.TextColumn("Company",  width="medium"),
                "title":      st.column_config.TextColumn("Role",     width="large"),
                "score":      st.column_config.NumberColumn("Match",  min_value=0, max_value=10, format="%d ⭐", width="small"),
                "relevancy":  st.column_config.TextColumn("Tier",     width="small"),
                "source":     st.column_config.TextColumn("Via",      width="small"),
                "found_date": st.column_config.TextColumn("Found",    width="small"),
                "status":     st.column_config.SelectboxColumn(
                                  "Status", options=STATUS_OPTIONS, required=True, width="medium"
                              ),
                "notes":      st.column_config.TextColumn("Notes",    width="large"),
                "url":        st.column_config.LinkColumn("Link",     width="small", display_text="View ↗"),
            },
            disabled=["company", "title", "score", "relevancy", "source", "found_date", "url"],
            hide_index=True,
            use_container_width=True,
            height=min(80 + 45 * len(df_tab), 480),
            key=f"editor_{user}_{min_score}_{tab_label}",
        )

        # Detect + save changes
        orig = df_tab[["status", "notes"]]
        edtd = edited[["status", "notes"]]
        mask = ~orig.eq(edtd).all(axis=1)
        if mask.any():
            changed = edited[mask][["job_id", "status", "notes"]]
            bulk_save(user, changed)
            for _, r in changed.iterrows():
                idx = st.session_state[cache_key]["job_id"] == r["job_id"]
                st.session_state[cache_key].loc[idx, "status"] = r["status"]
                st.session_state[cache_key].loc[idx, "notes"]  = r["notes"]
            st.toast(f"Saved {mask.sum()} update(s) ✓", icon="✅")


# ─── Job detail panel ─────────────────────────────────────────────────────────

st.markdown("<br>", unsafe_allow_html=True)
st.markdown(
    '<div style="font-size:20px;font-weight:700;color:#0f172a;margin-bottom:12px">Job Details</div>',
    unsafe_allow_html=True,
)

if df_view.empty:
    st.info("No jobs match your search or filters.")
else:
    # Dropdown with rich labels
    detail_labels = df_view.apply(
        lambda r: f"{r['company']}  —  {r['title']}  ·  {r['score']}/10  [{r['status']}]", axis=1
    ).tolist()
    selected_label  = st.selectbox("Select job", detail_labels, label_visibility="collapsed", key=f"detail_{user}")
    selected_idx    = detail_labels.index(selected_label)
    selected_row    = df_view.iloc[selected_idx]
    job_id          = selected_row["job_id"]

    scorecard = get_scorecard(user, job_id)
    gap       = get_gap(user, job_id)
    jd_text   = get_jd(user, job_id)

    # Job meta bar
    score   = scorecard.get("score", selected_row["score"]) if scorecard else selected_row["score"]
    urgency = scorecard.get("urgency", "") if scorecard else ""
    url     = scorecard.get("url", selected_row["url"]) if scorecard else selected_row["url"]

    meta_pills = score_badge_html(int(score))
    if urgency:
        urg_c = {"HIGH": "#ef4444", "MEDIUM": "#f59e0b"}.get(urgency, "#6b7280")
        meta_pills += f'&nbsp;{skill_tag_html(f"🔥 {urgency}", urg_c, urg_c + "18")}'
    meta_pills += f'&nbsp;{status_pill_html(selected_row["status"])}'
    if url:
        meta_pills += f'&nbsp;&nbsp;<a href="{url}" target="_blank" style="font-size:13px;color:#6366f1;font-weight:500;text-decoration:none">View Job ↗</a>'

    st.markdown(
        f'<div style="background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px 22px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,0.06)">'
        f'<div style="font-size:18px;font-weight:700;color:#0f172a">{selected_row["company"]}</div>'
        f'<div style="font-size:15px;color:#475569;margin:2px 0 10px">{selected_row["title"]}</div>'
        f'{meta_pills}'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Quick status buttons
    st.markdown('<div style="font-size:12px;color:#64748b;font-weight:600;margin-bottom:6px">QUICK UPDATE</div>', unsafe_allow_html=True)
    btn_cols = st.columns(len(STATUS_OPTIONS))
    for i, (status_opt, btn_col) in enumerate(zip(STATUS_OPTIONS, btn_cols)):
        m = STATUS_META[status_opt]
        is_current = selected_row["status"] == status_opt
        with btn_col:
            btn_style = "primary" if is_current else "secondary"
            if st.button(
                f"{m['icon']} {status_opt}",
                key=f"quick_{job_id}_{status_opt}",
                type=btn_style,
                use_container_width=True,
            ):
                upsert_status(user, job_id, status_opt)
                idx = st.session_state[cache_key]["job_id"] == job_id
                st.session_state[cache_key].loc[idx, "status"] = status_opt
                st.toast(f"Marked as {status_opt} ✓", icon=m["icon"])
                st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)
    detail_left, detail_right = st.columns(2)

    with detail_left:
        # Score reason card
        if scorecard and scorecard.get("reason"):
            st.markdown(
                f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:16px 18px">'
                f'<div style="font-size:12px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px">Why this match</div>'
                f'<div style="font-size:14px;color:#1e293b;line-height:1.6">{scorecard["reason"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # Missing skills
        req_miss  = scorecard.get("required_skills_missing", []) if scorecard else []
        pref_miss = scorecard.get("preferred_skills_missing", []) if scorecard else []
        if req_miss or pref_miss:
            st.markdown("<br>", unsafe_allow_html=True)
            section_header("Skills to build")
            html = ""
            for s in req_miss:
                html += skill_tag_html(s, "#b91c1c", "#fee2e2")
            for s in pref_miss[:5]:
                html += skill_tag_html(s, "#b45309", "#fef3c7")
            st.markdown(html, unsafe_allow_html=True)

    with detail_right:
        # Gap analysis
        if gap:
            has_req  = gap.get("candidate_has_required", [])
            miss_req = gap.get("candidate_missing_required", [])
            has_pref = gap.get("candidate_has_preferred", [])

            if has_req:
                section_header("✅ You already have")
                html = "".join(skill_tag_html(s, "#15803d", "#dcfce7") for s in has_req)
                st.markdown(html, unsafe_allow_html=True)
            if miss_req:
                st.markdown("<br>", unsafe_allow_html=True)
                section_header("❌ Gaps to address")
                html = "".join(skill_tag_html(s, "#b91c1c", "#fee2e2") for s in miss_req)
                st.markdown(html, unsafe_allow_html=True)
            if has_pref:
                st.markdown("<br>", unsafe_allow_html=True)
                section_header("⭐ Bonus skills you have")
                html = "".join(skill_tag_html(s, "#6366f1", "#eef2ff") for s in has_pref)
                st.markdown(html, unsafe_allow_html=True)
        else:
            st.info("Run the full pipeline to get skill gap analysis for this job.")

        # Notes
        st.markdown("<br>", unsafe_allow_html=True)
        section_header("Your notes")
        current_notes = str(selected_row["notes"]) if selected_row["notes"] else ""
        new_notes = st.text_area(
            "Notes",
            value=current_notes,
            placeholder="Add interview notes, referral contacts, follow-up dates…",
            height=100,
            label_visibility="collapsed",
            key=f"notes_{job_id}",
        )
        if new_notes != current_notes:
            upsert_status(user, job_id, selected_row["status"], new_notes)
            idx = st.session_state[cache_key]["job_id"] == job_id
            st.session_state[cache_key].loc[idx, "notes"] = new_notes
            st.toast("Notes saved ✓", icon="💾")

    # JD preview
    if jd_text:
        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("📄 Full job description"):
            st.markdown(
                f'<div style="font-size:13px;color:#475569;line-height:1.7;white-space:pre-wrap">{jd_text}</div>',
                unsafe_allow_html=True,
            )
