import json
import os
import subprocess
import sys
import time

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=False)
except ImportError:
    pass

from modules.article_writer import METHODOLOGY_LABELS
from modules.api_key_store import save_api_keys as persist_api_keys
from modules.gsheet_logger import GSheetLogger
from modules.project_manager import ProjectManager
from modules.runtime_keys import (
    KEY_NAMES,
    collect_runtime_api_key_sources,
    apply_resolved_api_keys,
    is_real_api_key as _shared_is_real_api_key,
    resolve_api_keys,
    snapshot_api_keys,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
CREDS_PATH = os.path.join(BASE_DIR, "gen-lang-client-0396271616-70425b3ad4fb.json")
DB_PATH = os.path.join(BASE_DIR, "database_v2.csv")
JOB_FILE = os.path.join(BASE_DIR, "job_queue.json")
LOCK_FILE = os.path.join(BASE_DIR, "worker_lock.txt")
ERROR_LOG_PATH = os.path.join(BASE_DIR, "worker_error.log")
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1i_lgFmoB1LJq2Lt01CwDlOk3hVbQxPiZ4LqGqf8mgwM"


def _get_build_version() -> str:
    """Return a stable build identifier for the current checkout."""
    candidates = [
        os.environ.get("STREAMLIT_GITHUB_COMMIT_SHA", "").strip(),
        os.environ.get("GIT_COMMIT", "").strip(),
        os.environ.get("COMMIT_SHA", "").strip(),
        os.environ.get("BUILD_SHA", "").strip(),
    ]
    for candidate in candidates:
        if candidate:
            return candidate[:12]

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=BASE_DIR,
            timeout=5,
            check=False,
        )
        sha = (result.stdout or "").strip()
        if sha:
            return sha[:12]
    except Exception:
        pass

    return "unknown"


BUILD_VERSION = _get_build_version()


def _get_creds_for_gsheet() -> tuple[dict | None, str | None]:
    """
    Lấy credentials cho GSheet.
    Priority:
      1. secrets.json file (local, .gitignored — local persist)
      2. st.secrets["gsheet_credentials"] (Cloud Secrets dashboard — cloud persist)
      3. st.session_state["gsheet_creds_data"] (upload trong app — cloud ephemeral)
      4. CREDS_PATH file (local service account JSON)
    Returns (creds_data, creds_path).
    """
    import json as _json

    # ① secrets.json file (local — bỏ qua trên Cloud vì file không tồn tại trong container)
    _json_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        ".streamlit", "secrets.json"
    )
    if os.path.exists(_json_path):
        try:
            with open(_json_path, "r", encoding="utf-8") as _f:
                _file_creds = _json.load(_f)
            if _file_creds.get("private_key"):
                return _file_creds, None
        except Exception:
            pass

    # ② st.secrets (Cloud Secrets dashboard — persist trên Cloud)
    try:
        import streamlit as st
        _raw = st.secrets.get("gsheet_credentials", None)
        if _raw is not None:
            if isinstance(_raw, dict) and _raw.get("private_key"):
                return _raw, None
            elif isinstance(_raw, str):
                try:
                    _parsed = _json.loads(_raw)
                    if isinstance(_parsed, dict) and _parsed.get("private_key"):
                        return _parsed, None
                except Exception:
                    pass
    except Exception:
        pass  # không phải Streamlit context

    # ③ session_state uploaded file (Cloud ephemeral — chỉ tồn tại trong 1 session)
    try:
        import streamlit as st
        _session = st.session_state.get("gsheet_creds_data")
        if _session and isinstance(_session, dict) and _session.get("private_key"):
            return _session, None
    except Exception:
        pass

    # ④ Local file (chỉ tồn tại trên máy user)
    if os.path.exists(CREDS_PATH):
        return None, CREDS_PATH

    return None, None


def _get_valid_gsheet_creds_with_source() -> tuple[dict | None, str | None, str]:
    import json as _json
    from modules.gsheet_logger import _normalize_service_account_info, _validate_private_key_pem

    def _valid_creds_dict(value):
        if not isinstance(value, dict) or not value.get("private_key"):
            return None
        normalized = _normalize_service_account_info(value)
        key_ok, _ = _validate_private_key_pem(normalized.get("private_key", ""))
        return normalized if key_ok else None

    def _valid_creds_file(path: str) -> bool:
        try:
            with open(path, "r", encoding="utf-8") as _f:
                _data = _json.load(_f)
            return _valid_creds_dict(_data) is not None
        except Exception:
            return False

    try:
        import streamlit as st
        _session = st.session_state.get("gsheet_creds_data")
        _session_valid = _valid_creds_dict(_session) if _session else None
        if _session_valid:
            return _session_valid, None, "session_state"
    except Exception:
        pass

    _json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".streamlit", "secrets.json")
    if os.path.exists(_json_path):
        try:
            with open(_json_path, "r", encoding="utf-8") as _f:
                _file_creds = _json.load(_f)
            _file_valid = _valid_creds_dict(_file_creds)
            if _file_valid:
                return _file_valid, None, "local_secrets_json"
        except Exception:
            pass

    try:
        import streamlit as st
        _raw = st.secrets.get("gsheet_credentials", None)
        if isinstance(_raw, dict):
            _raw_valid = _valid_creds_dict(_raw)
            if _raw_valid:
                return _raw_valid, None, "st.secrets"
        elif isinstance(_raw, str):
            try:
                _parsed = _json.loads(_raw)
                _parsed_valid = _valid_creds_dict(_parsed)
                if _parsed_valid:
                    return _parsed_valid, None, "st.secrets"
            except Exception:
                pass
    except Exception:
        pass

    if os.path.exists(CREDS_PATH) and _valid_creds_file(CREDS_PATH):
        return None, CREDS_PATH, "local_service_account_json"

    return None, None, "missing"


def _get_valid_gsheet_creds() -> tuple[dict | None, str | None]:
    creds_data, creds_path, _ = _get_valid_gsheet_creds_with_source()
    return creds_data, creds_path


def _get_gsheet_creds() -> tuple[dict | None, str | None]:
    """Wrapper: gọi _get_creds_for_gsheet, trả về đầy đủ (dict HOẶC path)."""
    return _get_valid_gsheet_creds()

IS_CLOUD = bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("STREAMLIT_CLOUD"))

st.set_page_config(
    page_title="Content Brief Generator",
    page_icon="🧭",
    layout="wide",
)


def inject_ui_css() -> None:
    st.markdown(
        """
        <style>
        /* ══════════════════════════════════════════
           MODERN FLAT DESIGN — Clean, Minimal, Fast
           ══════════════════════════════════════════ */

        :root {
            --bg:        #f0f4f8;
            --surface:   #ffffff;
            --surface-2: #f8fafc;
            --border:    #e2e8f0;
            --ink:       #1a202c;
            --muted:     #64748b;
            --accent:    #3b82f6;
            --accent-2:  #10b981;
            --ok:        #22c55e;
            --danger:    #ef4444;
            --warn:      #f59e0b;
            --radius:    12px;
            --radius-lg: 18px;
            /* Soft elevation shadows (flat — no dual shadows) */
            --shadow-sm:  0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
            --shadow-md:  0 4px 6px rgba(0,0,0,0.07), 0 2px 4px rgba(0,0,0,0.04);
            --shadow-lg:  0 10px 15px rgba(0,0,0,0.08), 0 4px 6px rgba(0,0,0,0.04);
        }

        /* ── App Background ── */
        .stApp {
            background: var(--bg);
            color: var(--ink);
        }
        .block-container {
            padding-top: 1.5rem;
            padding-bottom: 1.5rem;
        }

        /* ── Sidebar ── */
        [data-testid="stSidebar"] {
            background: var(--surface) !important;
            border-right: 1px solid var(--border);
        }

        /* ── Tabs — flat pill style ── */
        div[data-testid="stTabs"] button {
            border-radius: 999px !important;
            padding: 0.35rem 1rem;
            background: transparent !important;
            color: var(--muted) !important;
            border: 1.5px solid var(--border) !important;
            font-weight: 500;
            font-size: 0.875rem;
            transition: all 0.18s ease !important;
            box-shadow: none !important;
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            background: var(--accent) !important;
            color: #ffffff !important;
            border-color: var(--accent) !important;
            box-shadow: var(--shadow-sm) !important;
        }
        div[data-testid="stTabs"] button:hover:not([aria-selected="true"]) {
            border-color: var(--accent) !important;
            color: var(--accent) !important;
        }

        /* ── Metric Cards — clean flat ── */
        div[data-testid="stMetric"] {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 1rem;
            box-shadow: var(--shadow-sm);
        }
        div[data-testid="stMetricLabel"] {
            color: var(--muted) !important;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            text-transform: uppercase;
        }
        div[data-testid="stMetricValue"] {
            color: var(--ink) !important;
            font-weight: 700;
            font-size: 1.5rem;
        }
        div[data-testid="stMetricDelta"] {
            font-size: 0.8rem;
        }

        /* ── Hero Banner ── */
        .hero-shell {
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            padding: 1.75rem;
            background:
                radial-gradient(circle at top right, rgba(59,130,246,0.12), transparent 28%),
                linear-gradient(135deg, #ffffff 0%, #f8fbff 100%);
            box-shadow: var(--shadow-md);
            margin-bottom: 1rem;
        }
        .hero-kicker {
            color: var(--accent);
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            margin-bottom: 0.4rem;
        }
        .hero-title {
            font-size: 1.75rem;
            font-weight: 800;
            color: var(--ink);
            line-height: 1.2;
            margin-bottom: 0.5rem;
        }
        .hero-copy {
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.6;
            max-width: 60rem;
        }

        /* ── Pill Badges ── */
        .pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.75rem;
        }
        .pill {
            background: var(--bg);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.3rem 0.75rem;
            color: var(--muted);
            font-size: 0.8rem;
            font-weight: 500;
            transition: all 0.15s ease;
        }
        .pill:hover {
            border-color: var(--accent);
            color: var(--accent);
        }
        .pill strong {
            color: var(--ink);
        }

        /* ── Panel Notes ── */
        .panel-note {
            border: 1px solid var(--border);
            border-left: 3px solid var(--accent);
            border-radius: var(--radius);
            background: var(--surface);
            padding: 0.85rem 1rem;
            box-shadow: var(--shadow-sm);
        }
        .panel-note h4 {
            margin: 0 0 0.25rem;
            color: var(--ink);
            font-size: 0.9rem;
            font-weight: 700;
        }
        .panel-note p {
            margin: 0;
            color: var(--muted);
            font-size: 0.85rem;
        }

        .section-kicker {
            margin: 0 0 0.35rem 0;
            color: var(--accent);
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }

        .section-copy {
            margin: 0 0 1rem 0;
            color: var(--muted);
            font-size: 0.9rem;
            line-height: 1.6;
        }

        .deck-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
            gap: 0.75rem;
            margin: 0.75rem 0 1rem 0;
        }

        .deck-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 0.9rem 1rem;
            box-shadow: var(--shadow-sm);
        }

        .deck-card.deck-card-tint {
            background: linear-gradient(180deg, rgba(59,130,246,0.06), rgba(255,255,255,1));
        }

        .deck-eyebrow {
            display: block;
            color: var(--muted);
            font-size: 0.74rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            margin-bottom: 0.3rem;
        }

        .deck-value {
            color: var(--ink);
            font-size: 1.15rem;
            font-weight: 800;
            line-height: 1.2;
        }

        .deck-meta {
            margin-top: 0.35rem;
            color: var(--muted);
            font-size: 0.82rem;
            line-height: 1.45;
        }

        .status-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 0.75rem;
            margin: 0.5rem 0 0.9rem 0;
        }

        .status-card {
            background: var(--surface-2);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 0.85rem 1rem;
            box-shadow: var(--shadow-sm);
        }

        .status-card strong {
            display: block;
            color: var(--ink);
            font-size: 0.98rem;
            margin-bottom: 0.15rem;
        }

        .status-card span {
            color: var(--muted);
            font-size: 0.82rem;
            line-height: 1.45;
        }

        .mono-caption {
            color: var(--muted);
            font-size: 0.78rem;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }

        /* ── Cards (st.container border=True) ── */
        [data-testid="stHorizontalBlock"] > div > div > [data-testid="stVerticalBlock"] > div > div[style*="border"],
        [data-testid="stHorizontalBlock"] [data-testid="stVerticalBlock"] > div > [style*="border"] {
            background: var(--surface) !important;
            border: 1px solid var(--border) !important;
            border-radius: var(--radius) !important;
            box-shadow: var(--shadow-sm) !important;
        }

        /* ── Form Inputs — flat with bottom border accent ── */
        div[data-testid="stTextInputRoot"] > div,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stSelectbox"] > div {
            background: var(--surface) !important;
            border: 1.5px solid var(--border) !important;
            border-radius: var(--radius) !important;
            transition: border-color 0.15s ease !important;
        }
        div[data-testid="stTextInputRoot"]:has(input:focus) > div,
        div[data-testid="stTextArea"]:has(textarea:focus) textarea,
        div[data-testid="stSelectbox"]:has([aria-expanded="true"]) > div {
            border-color: var(--accent) !important;
            box-shadow: 0 0 0 3px rgba(59,130,246,0.1) !important;
        }
        textarea, input, [data-baseweb="select"] input {
            color: var(--ink) !important;
            font-size: 0.9rem !important;
        }

        /* ── Buttons — flat with accent fill ── */
        .stButton > button,
        .stDownloadButton > button {
            border-radius: var(--radius) !important;
            border: none !important;
            background: var(--surface) !important;
            color: var(--ink) !important;
            font-weight: 600 !important;
            font-size: 0.875rem !important;
            box-shadow: var(--shadow-sm) !important;
            transition: all 0.15s ease !important;
            padding: 0.5rem 1rem !important;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover {
            box-shadow: var(--shadow-md) !important;
            transform: translateY(-1px);
            filter: brightness(0.97);
        }
        .stButton > button:active,
        .stDownloadButton > button:active {
            box-shadow: var(--shadow-sm) !important;
            transform: translateY(0);
            filter: brightness(0.95);
        }
        .stButton > button[kind="primary"] {
            background: var(--accent) !important;
            color: #ffffff !important;
        }
        .stButton > button[kind="primary"]:hover {
            background: #2563eb !important;
        }
        .stButton > button[kind="secondary"] {
            background: var(--bg) !important;
            color: var(--muted) !important;
            border: 1.5px solid var(--border) !important;
            box-shadow: none !important;
        }

        /* ── DataFrame — flat, clean rows ── */
        div[data-testid="stDataFrame"] {
            background: var(--surface) !important;
            border: 1px solid var(--border) !important;
            border-radius: var(--radius) !important;
            overflow: hidden;
            box-shadow: var(--shadow-sm);
        }
        /* Row striping */
        div[data-testid="stDataFrame"] tbody tr:nth-child(even) td {
            background: #f8fafc !important;
        }
        div[data-testid="stDataFrame"] thead th {
            background: var(--bg) !important;
            color: var(--muted) !important;
            font-weight: 700 !important;
            font-size: 0.75rem !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            border-bottom: 2px solid var(--border) !important;
        }
        div[data-testid="stDataFrame"] tbody td {
            color: var(--ink);
            font-size: 0.875rem;
        }

        /* ── Expander ── */
        div[data-testid="stExpander"] {
            background: var(--surface) !important;
            border: 1px solid var(--border) !important;
            border-radius: var(--radius) !important;
            box-shadow: var(--shadow-sm);
        }
        div[data-testid="stExpander"] details summary {
            color: var(--ink) !important;
            font-weight: 600;
        }

        /* ── Alerts / Info boxes ── */
        div[data-testid="stAlert"] {
            border-radius: var(--radius) !important;
            border: none !important;
            box-shadow: var(--shadow-sm) !important;
        }

        /* ── Lift Card ── */
        .lift-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius);
            padding: 0.9rem 1rem;
            box-shadow: var(--shadow-sm);
        }
        .lift-card strong {
            color: var(--ink);
            font-size: 1rem;
        }
        .lift-card span {
            color: var(--muted);
            display: block;
            margin-bottom: 0.2rem;
            font-size: 0.8rem;
        }

        /* ── Selectbox dropdown ── */
        [data-baseweb="popover"],
        [data-baseweb="menu"] {
            background: var(--surface) !important;
            border: 1px solid var(--border) !important;
            border-radius: var(--radius) !important;
            box-shadow: var(--shadow-lg) !important;
        }
        [data-baseweb="option"] {
            border-radius: 6px !important;
            font-size: 0.875rem !important;
        }
        [data-baseweb="option"]:hover,
        [data-baseweb="option"]:focus {
            background: var(--bg) !important;
        }

        /* ── Progress bar ── */
        [data-testid="stProgressBar"] > div > div {
            background: var(--accent) !important;
            border-radius: 999px;
        }

        /* ── Subheaders ── */
        .stMarkdownContainer h1,
        .stMarkdownContainer h2,
        .stMarkdownContainer h3 {
            color: var(--ink);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def init_state() -> None:
    defaults = {
        "show_project_form": False,
        "edit_project_id": None,
        "confirm_delete_pid": None,
        "batch_running": False,
        "batch_keywords": [],
        "batch_idx": 0,
        "batch_results": [],
        "batch_config": {},
        "batch_project_id": None,
        "batch_sheet_url": "",
        "batch_last_event": "",
        "batch_current_keyword": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def project_to_dict(project) -> dict:
    if not project:
        return {
            "name": "",
            "brand_name": "",
            "domain": "",
            "company_full_name": "",
            "industry": "",
            "main_products": "",
            "usp": "",
            "target_customers": "",
            "competitor_brands": "",
            "tone": "",
            "technical_standards": "",
            "geo_keywords": "",
            "hotline": "",
            "email": "",
            "address": "",
            "warehouse": "",
        }

    return {
        "name": project.name,
        "brand_name": project.brand_name,
        "domain": project.domain,
        "company_full_name": project.company_full_name,
        "industry": project.industry,
        "main_products": project.main_products,
        "usp": project.usp,
        "target_customers": project.target_customers,
        "competitor_brands": project.competitor_brands,
        "tone": project.tone,
        "technical_standards": project.technical_standards,
        "geo_keywords": project.geo_keywords,
        "hotline": project.hotline,
        "email": project.email,
        "address": project.address,
        "warehouse": project.warehouse,
    }


def save_api_keys(
    serper_key: str,
    openai_key: str,
) -> str:
    return persist_api_keys(
        env_path=ENV_PATH,
        serper_key=serper_key,
        openai_key=openai_key,
    )



def _is_real_api_key(value: str, name: str) -> bool:
    return _shared_is_real_api_key(value, name)


def _resolve_api_key_info(name: str) -> tuple[str, str]:
    """
    Return (api_key, source) using strict precedence:
    session_state > st.secrets > process env.
    """
    resolved_keys, resolved_sources = resolve_api_keys(collect_runtime_api_key_sources())
    return resolved_keys.get(name, ""), resolved_sources.get(name, "missing")


def _run_keyword_metrics_live_test(keyword: str) -> dict:
    """Legacy no-op kept to avoid breaking old external imports."""
    return {"ok": False, "error": "Deprecated helper in tool-only mode."}



def _sync_api_keys_to_env() -> dict:
    """
    Phase 44: Đồng bộ API keys từ session_state / st.secrets → os.environ + config.LLM_CONFIG.
    Returns a dict with debug info for logging.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    try:
        source_maps = collect_runtime_api_key_sources()
        debug = {
            "secrets_keys": {},
            "session_keys": {},
            "env_keys": {},
            "merged": {},
            "llm_config_key": "(none)",
            "llm_config_updated": False,
            "error": "(none)",
            "openai_source": "(none)",
            "serper_source": "(none)",
        }
        debug["session_keys"] = snapshot_api_keys([source_maps[0]])["session_state"]
        debug["secrets_keys"] = snapshot_api_keys([source_maps[1]])["st.secrets"]
        debug["env_keys"] = snapshot_api_keys([source_maps[2]])["process_env"]

        resolved_keys, resolved_sources = resolve_api_keys(source_maps)
        debug["merged"] = {
            k: (v[:12] + "..." if v else "(empty)")
            for k, v in resolved_keys.items()
        }

        try:
            import config as _config
            from config import LLM_CONFIG
            apply_resolved_api_keys(
                resolved_keys,
                resolved_sources,
                config_module=_config,
                llm_config=LLM_CONFIG,
            )
            openai_val = resolved_keys.get("OPENAI_API_KEY", "")
            serper_val = resolved_keys.get("SERPER_API_KEY", "")
            if _is_real_api_key(openai_val, "OPENAI_API_KEY"):
                debug["llm_config_key"] = openai_val[:12] + "..."
                debug["llm_config_updated"] = True
                debug["openai_source"] = resolved_sources.get("OPENAI_API_KEY", "missing")
            if _is_real_api_key(serper_val, "SERPER_API_KEY"):
                debug["serper_source"] = resolved_sources.get("SERPER_API_KEY", "missing")
            if not _is_real_api_key(openai_val, "OPENAI_API_KEY"):
                _log.warning(
                    "[KEY-SYNC] No valid OPENAI_API_KEY found. "
                    "session='%s', secrets='%s', env='%s'",
                    debug["session_keys"].get("OPENAI_API_KEY", ""),
                    debug["secrets_keys"].get("OPENAI_API_KEY", ""),
                    debug["env_keys"].get("OPENAI_API_KEY", ""),
                )
        except Exception as e:
            debug["error"] = str(e)
            _log.error("[KEY-SYNC] Failed to patch LLM_CONFIG: %s", e)
    except Exception as e:
        debug = {
            "secrets_keys": {},
            "session_keys": {},
            "env_keys": {},
            "merged": {},
            "llm_config_key": "(none)",
            "llm_config_updated": False,
            "error": str(e),
            "openai_source": "(none)",
            "serper_source": "(none)",
        }
        _log.critical("[KEY-SYNC] FATAL: Cannot import streamlit or sync keys: %s", e)
    return debug


def save_credentials_file(uploaded_file) -> str:
    # Phase 40: Đọc bytes trực tiếp, hash private_key trước+sau để xác nhận không corrupt
    import hashlib
    from modules.gsheet_logger import _normalize_service_account_info, _validate_private_key_pem
    try:
        raw_bytes = uploaded_file.getvalue()
    except Exception:
        try:
            uploaded_file.seek(0)
            raw_bytes = uploaded_file.read()
        except Exception as e:
            return f"Không đọc được file: {e}"
    try:
        creds_data = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        return f"Không parse được JSON: {e}"
    if not isinstance(creds_data, dict):
        return "Credentials JSON phải là object/dict."
    creds_data = _normalize_service_account_info(creds_data)
    key_ok, key_error = _validate_private_key_pem(creds_data.get("private_key", ""))
    if not key_ok:
        return f"Credentials không hợp lệ: {key_error}"
    # Hash private_key TRƯỚC KHI GHI
    pk_before = creds_data.get("private_key", "")
    hash_before = hashlib.sha256(pk_before.encode()).hexdigest()
    # Ghi file bằng raw bytes — không decode/encode thêm
    try:
        with open(CREDS_PATH, "w", encoding="utf-8") as file:
            json.dump(creds_data, file, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Lỗi ghi file credentials: {e}"
    # Hash SAU KHI ĐỌC LẠI để xác nhận
    try:
        with open(CREDS_PATH, "rb") as f:
            raw_read = f.read()
        verify = json.loads(raw_read.decode("utf-8"))
        pk_after = verify.get("private_key", "")
        hash_after = hashlib.sha256(pk_after.encode()).hexdigest()
        if hash_before != hash_after:
            return f"Lỗi: private_key bị corrupt khi ghi (hash mismatch). Thử upload lại."
    except Exception as e:
        return f"Lỗi xác nhận file: {e}"

    # Phase 42b: Lưu dict vào session_state (Cloud ephemeral filesystem fallback)
    # Trên Cloud, file upload không persist qua redeploy — dùng session_state
    try:
        import streamlit as st
        st.session_state["gsheet_creds_data"] = creds_data
    except Exception:
        pass

    return f"Đã lưu credentials ({creds_data.get('client_email', '?')}) — hash OK"


def test_gsheet_connection(sheet_url: str) -> tuple[bool, str]:
    """
    Test kết nối GSheet. Luôn debug chi tiết để người dùng biết lỗi ở đâu.
    """
    from modules.gsheet_logger import GSheetLogger, _normalize_service_account_info, _validate_private_key_pem

    # ── Debug: kiểm tra secrets đang đọc được gì ────────────────────────────
    debug_lines = []

    try:
        import streamlit as st
        raw_secret = st.secrets.get("gsheet_credentials", None)
        if raw_secret is not None:
            debug_lines.append(f"  type(gsheet_credentials) = {type(raw_secret).__name__}")
            if isinstance(raw_secret, dict):
                pk = raw_secret.get("private_key", "")
                debug_lines.append(f"  private_key length = {len(pk)}")
                debug_lines.append(f"  private_key starts = {pk[:40]!r}...")
                debug_lines.append(f"  private_key ends   = ...{pk[-40:]!r}")
                debug_lines.append(f"  client_email = {raw_secret.get('client_email', 'MISSING')}")
            else:
                debug_lines.append(f"  WARNING: gsheet_credentials is NOT a dict! type={type(raw_secret)}")
                debug_lines.append(f"  value preview = {str(raw_secret)[:100]!r}")
        else:
            debug_lines.append("  gsheet_credentials not found in st.secrets")
    except Exception as sec_e:
        debug_lines.append(f"  st.secrets error: {sec_e}")

    creds_data, creds_path, creds_source = _get_valid_gsheet_creds_with_source()
    debug_lines.append(f"  creds_data = {type(creds_data).__name__} ({'None' if creds_data is None else 'found'})")
    debug_lines.append(f"  creds_path = {creds_path or 'None'}")
    debug_lines.append(f"  creds_source = {creds_source}")

    # ── ① Cloud Secrets: dict credentials ─────────────────────────────────────
    if creds_data:
        debug_lines.append(f"  → Dùng dict từ nguồn: {creds_source}")
        debug_lines.append(f"  pk len={len(creds_data.get('private_key',''))}, email={creds_data.get('client_email','?')}")
        print(f"[TEST GSHEET] creds_data type={type(creds_data).__name__}, pk_len={len(creds_data.get('private_key',''))}")

        try:
            from google.auth.exceptions import RefreshError
            glog = GSheetLogger(creds_data=creds_data, sheet_url=sheet_url)
            # Gọi connect — phần này sẽ in [GSHEET DEBUG] ra server stdout
            try:
                if glog.connect():
                    title = glog.sheet.title
                    row_count = len(glog.worksheet.get_all_values())
                    return True, f"Kết nối OK. Nguồn credentials: {creds_source}. Sheet: '{title}', {row_count} dòng."
                else:
                    err = glog._last_error or "không rõ"
                    debug_msg = "DEBUG secrets đang đọc:\n" + "\n".join(debug_lines)
                    return False, f"Kết nối GSheet thất bại. Nguồn credentials: {creds_source}.\n\n{debug_msg}\n\nLỗi:\n{err}"
            except RefreshError as rfe:
                # RefreshError xảy ra bên TRONG connect() — bắt riêng để hiện chi tiết
                debug_msg = "DEBUG secrets đang đọc:\n" + "\n".join(debug_lines)
                pk = creds_data.get("private_key", "")
                return False, (
                    f"Kết nối GSheet thất bại — JWT Signature lỗi.\n\n"
                    f"{debug_msg}\n\n"
                    f"DEBUG connect() output (xem View logs):\n"
                    f"  pk_length={len(pk)}\n"
                    f"  pk_starts={pk[:50]!r}\n"
                    f"  pk_ends=...{pk[-30:]!r}\n"
                    f"  token_uri={creds_data.get('token_uri','?')}\n\n"
                    f"Chi tiết lỗi: {rfe}\n\n"
                    f"Nguyên nhân thường gặp:\n"
                    f"  1. Private key trong secrets bị corrupt/sai\n"
                    f"  2. Service account chưa được chia sẻ quyền trên Google Sheet\n"
                    f"  3. Google Cloud project bị disable\n\n"
                    f"Xem thêm: Help > View logs (server stdout có [GSHEET DEBUG] prints)"
                )
        except Exception as e:
            import traceback
            debug_msg = "DEBUG secrets đang đọc:\n" + "\n".join(debug_lines)
            return False, f"Lỗi kết nối:\n{debug_msg}\n\nChi tiết:\n{e}\n{traceback.format_exc()}"

    # ── ② Local file ───────────────────────────────────────────────────────────
    if not creds_path:
        debug_msg = "DEBUG:\n" + "\n".join(debug_lines)
        return False, f"Không tìm thấy credentials.\n{debug_msg}\n\nHướng dẫn: Thêm gsheet_credentials vào Streamlit Cloud > Settings > Secrets."

    debug_lines.append(f"  → Dùng file local: {creds_source}")
    import hashlib
    try:
        with open(creds_path, "rb") as f:
            raw = f.read()
        creds_data_local = json.loads(raw.decode("utf-8"))
    except FileNotFoundError:
        return False, f"Credentials file không tìm thấy tại: {creds_path}"
    except Exception as e:
        return False, f"Lỗi đọc credentials: {e}"

    if "private_key" not in creds_data_local:
        return False, f"Credentials thiếu 'private_key'. Fields: {list(creds_data_local.keys())}"
    if "client_email" not in creds_data_local:
        return False, f"Credentials thiếu 'client_email'. Fields: {list(creds_data_local.keys())}"

    try:
        glog = GSheetLogger(creds_path=creds_path, sheet_url=sheet_url)
        if glog.connect():
            title = glog.sheet.title
            row_count = len(glog.worksheet.get_all_values())
            return True, f"Kết nối OK. Nguồn credentials: {creds_source}. Sheet: '{title}', {row_count} dòng."
        else:
            return False, f"Kết nối GSheet thất bại. Nguồn credentials: {creds_source}.\nLỗi chi tiết:\n{glog._last_error or 'không rõ'}"
    except Exception as e:
        import traceback
        return False, f"Lỗi: {e}\n{traceback.format_exc()}"


def normalize_uploaded_keywords(uploaded_csv) -> tuple[list[str], str]:
    try:
        df = pd.read_csv(uploaded_csv)
    except Exception as exc:
        return [], f"Không đọc được CSV: {exc}"

    if df.empty:
        return [], "CSV đang rỗng."

    normalized = {str(col).strip().lower(): col for col in df.columns}
    target_col = normalized.get("keyword")
    if target_col is None:
        if len(df.columns) == 1:
            target_col = df.columns[0]
        else:
            return [], "CSV cần có cột `Keyword`, hoặc chỉ 1 cột dữ liệu."

    keywords = [str(value).strip() for value in df[target_col].dropna().tolist() if str(value).strip()]
    return keywords, ""


def load_database() -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    try:
        df = pd.read_csv(DB_PATH, encoding="utf-8-sig")
        if "Báo cáo phân tích dữ liệu" in df.columns:
            df = df.drop(columns=["Báo cáo phân tích dữ liệu"], errors="ignore")
        return df
    except Exception:
        return pd.DataFrame()


def read_log_tail(path: str, max_lines: int = 40) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as file:
            lines = file.readlines()
        return "".join(lines[-max_lines:])
    except Exception:
        return ""


def compute_status_metrics(df: pd.DataFrame) -> dict:
    if df.empty or "Trạng thái" not in df.columns:
        return {"total": 0, "done": 0, "running": 0, "error": 0}

    statuses = df["Trạng thái"].fillna("").astype(str)
    return {
        "total": len(df),
        "done": int(statuses.str.contains("Done", case=False, na=False).sum()),
        "running": int(statuses.str.contains("Running", case=False, na=False).sum()),
        "error": int(statuses.str.contains("Error", case=False, na=False).sum()),
    }


def _api_key(name: str) -> str:
    """
    Phase 43: Lấy API key — 3 nguồn:
    1. session_state.api_keys (user entered in UI)
    2. os.environ (local .env / process env)
    3. st.secrets (Cloud persistent)
    """
    value, _source = _resolve_api_key_info(name)
    return value


def validate_run_request(keywords: list[str], enable_serp: bool) -> list[str]:
    problems = []
    if not keywords:
        problems.append("Cần nhập ít nhất 1 keyword.")
    if not _api_key("OPENAI_API_KEY"):
        problems.append("Thiếu `OPENAI_API_KEY`.")
    if enable_serp and not _api_key("SERPER_API_KEY"):
        problems.append("Đã bật SERP nhưng chưa có `SERPER_API_KEY`.")
    return problems


def build_job_payload(
    keywords: list[str],
    sheet_url: str,
    enable_serp: bool,
    enable_network: bool,
    enable_context: bool,
    enable_linking: bool,
    methodology: str,
    active_project,
) -> dict:
    # Phase 36: Dùng credentials từ session (đã upload) hoặc local file
    creds_for_job = CREDS_PATH  # luôn pass file local, vì worker chạy local
    resolved_api_keys = {}
    resolved_api_key_sources = {}
    for key_name in KEY_NAMES:
        resolved_api_keys[key_name], resolved_api_key_sources[key_name] = _resolve_api_key_info(key_name)
    # Phase 4.1: Include schema version for worker validation
    return {
        "schema_version": 1,
        "build_version": BUILD_VERSION,
        "keywords": keywords,
        "creds_path": creds_for_job,
        "sheet_url": sheet_url,
        "resolved_api_keys": resolved_api_keys,
        "resolved_api_key_sources": resolved_api_key_sources,
        "config": {
            "enable_serp": enable_serp,
            "enable_network": enable_network,
            "enable_context": enable_context,
            "enable_linking": enable_linking,
            "methodology": methodology,
            "project_id": active_project.id if active_project else None,
        },
        "output_dir": "output_ui",
    }


def write_job_payload(job_data: dict) -> None:
    with open(JOB_FILE, "w", encoding="utf-8") as file:
        json.dump(job_data, file, ensure_ascii=False, indent=2)


def _is_process_alive(pid: int) -> bool:
    """Kiểm tra PID còn sống không (cross-platform)."""
    try:
        if os.name == "nt":
            # Windows: dùng tasklist kiểm tra PID tồn tại
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        else:
            # Unix: gửi signal 0 → không kill, chỉ kiểm tra
            os.kill(pid, 0)
            return True
    except (ProcessLookupError, PermissionError, OSError, subprocess.TimeoutExpired):
        return False


def start_local_worker() -> None:
    # Phase 1.2: Validate stale lock — nếu lock file tồn tại nhưng PID đã chết → xóa
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE, "r", encoding="utf-8", errors="ignore") as f:
            stored_pid = f.read().strip()
        if stored_pid and stored_pid != "STARTING" and stored_pid.isdigit():
            if not _is_process_alive(int(stored_pid)):
                try:
                    os.remove(LOCK_FILE)
                except OSError:
                    pass

    # Phase 36: Dùng PIPE để worker tự quản lý file write, tránh fd leak
    # Khi dùng PIPE, parent không giữ open() handle — worker dup2() vào stdout/stderr
    # Sau đó parent đóng PIPE ngay, worker vẫn ghi được vì dup2() đã copy fd
    error_file = open(ERROR_LOG_PATH, "a", encoding="utf-8", buffering=1)  # keep open for worker dup
    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", "worker.py"],
            cwd=BASE_DIR,
            stdout=error_file,
            stderr=error_file,
        )
    except Exception as e:
        error_file.close()
        raise RuntimeError(f"Không khởi động được worker: {e}") from e
    # Đóng file handle ở parent — dup2() đã copy fd vào child, child vẫn ghi được
    error_file.close()
    # Ghi PID ra lock file
    with open(LOCK_FILE, "w", encoding="utf-8") as file:
        file.write(str(proc.pid))


def stop_local_worker() -> None:
    pid_value = None
    if os.path.exists(LOCK_FILE):
        with open(LOCK_FILE, "r", encoding="utf-8", errors="ignore") as file:
            pid_value = file.read().strip()

    if pid_value and pid_value.isdigit():
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/PID", pid_value], check=False, capture_output=True)
        else:
            subprocess.run(["kill", "-9", pid_value], check=False, capture_output=True)

    if os.path.exists(LOCK_FILE):
        os.remove(LOCK_FILE)


def reset_database(sheet_url: str) -> list[str]:
    messages = []

    if os.path.exists(DB_PATH):
        try:
            # Phase 36: Tạo file CSV mới với headers sạch — không cần đọc file cũ
            from modules.csv_logger import DB_HEADERS
            fresh_df = pd.DataFrame(columns=DB_HEADERS)
            fresh_df.to_csv(DB_PATH, index=False, encoding="utf-8-sig")
            messages.append("Đã reset database CSV cục bộ.")
        except Exception as exc:
            messages.append(f"Reset CSV lỗi: {exc}")

    # Phase 41: Ưu tiên dict từ Cloud Secrets > file path local.
    creds_data, creds_path = _get_gsheet_creds()
    if not creds_data and not creds_path:
        messages.append("Không tìm thấy credentials. Upload file JSON hoặc cấu hình Streamlit Secrets.")
        return messages

    glog = GSheetLogger(creds_data=creds_data, creds_path=creds_path, sheet_url=sheet_url)
    if glog.connect():
        try:
            glog.worksheet.batch_clear(["A2:Q10000"])
            messages.append("Đã xóa dữ liệu cũ trên Google Sheet.")
        except Exception as exc:
            messages.append(f"Không xóa được Google Sheet: {exc}")
    else:
        messages.append("Kết nối Google Sheet thất bại. Kiểm tra lại credentials.")

    return messages


def queue_cloud_batch(job_data: dict) -> None:
    st.session_state.batch_running = True
    st.session_state.batch_keywords = job_data["keywords"]
    st.session_state.batch_idx = 0
    st.session_state.batch_results = []
    st.session_state.batch_config = job_data["config"]
    st.session_state.batch_project_id = job_data["config"].get("project_id")
    st.session_state.batch_sheet_url = job_data["sheet_url"]
    st.session_state.batch_last_event = "Cloud batch đã được khởi tạo."
    st.session_state.batch_current_keyword = ""


def process_cloud_batch_if_needed() -> None:
    """Phase 44: Two-phase batch processor.

    Phase 1 (rerun N):  Set progress + flag → st.rerun()
    Phase 2 (rerun N+1): Clear flag → process keyword → next or finish
    """
    if not IS_CLOUD or not st.session_state.get("batch_running"):
        return

    keywords = st.session_state.batch_keywords
    batch_idx = st.session_state.batch_idx
    if batch_idx >= len(keywords):
        st.session_state.batch_running = False
        st.session_state.batch_current_keyword = ""
        st.session_state.batch_last_event = (
            f"Hoan tat {len(st.session_state.batch_results)}/{len(keywords)} keywords tren Streamlit Cloud."
        )
        return

    keyword = keywords[batch_idx]
    st.session_state.batch_current_keyword = keyword

    # Phase 44: TWO-PHASE — avoid showing blank screen during processing
    _flag_key = f"_batch_phase2_{batch_idx}"
    if not st.session_state.get(_flag_key):
        # Phase 1: Show progress, set flag, rerun
        st.session_state[_flag_key] = True
        st.session_state.batch_last_event = (
            f"[{batch_idx+1}/{len(keywords)}] Bat dau xu ly: {keyword}"
        )
        st.rerun()
        return

    # Phase 2: Clear flag, do actual work
    st.session_state.pop(_flag_key, None)

    try:
        project = None
        project_id = st.session_state.batch_project_id
        if project_id:
            pm = ProjectManager()
            project = pm.get_by_id(project_id)

        # Phase 44: Sync keys
        dbg = _sync_api_keys_to_env()
        import logging as _log
        _dl = _log.getLogger(__name__)
        _dl.info(
            "[BATCH-DEBUG] secrets=%s | session=%s | merged=%s | llm_updated=%s | llm_key=%s",
            dbg["secrets_keys"], dbg["session_keys"], dbg["merged"],
            dbg["llm_config_updated"], dbg["llm_config_key"]
        )

        if not dbg["llm_config_updated"]:
            _dl.warning("[BATCH-GUARD] OPENAI_API_KEY not resolved in sync helper; worker will fail fast if needed.")

        from main_generator import _process_single_topic

        _creds_data, _creds_path = _get_gsheet_creds()
        glog = None
        if _creds_data or _creds_path:
            glog = GSheetLogger(
                creds_data=_creds_data,
                creds_path=_creds_path,
                sheet_url=st.session_state.batch_sheet_url or DEFAULT_SHEET_URL,
            )
            if not glog.connect():
                glog = None

        result = _process_single_topic(
            topic=keyword,
            enable_serp=st.session_state.batch_config.get("enable_serp", True),
            enable_network=st.session_state.batch_config.get("enable_network", False),
            enable_context=st.session_state.batch_config.get("enable_context", False),
            enable_linking=st.session_state.batch_config.get("enable_linking", True),
            methodology=st.session_state.batch_config.get("methodology", "auto"),
            output_dir="output_ui",
            total_steps=1,
            glog=glog,
            csv_log=None,
            csv_row=-1,
            project=project,
        )
        if result:
            st.session_state.batch_results.append(
                {"keyword": keyword, "status": "done", "file": result}
            )
            st.session_state.batch_last_event = f"Xong [{batch_idx+1}/{len(keywords)}]: {keyword}"
        else:
            st.session_state.batch_results.append(
                {"keyword": keyword, "status": "error: blocked by worker preflight", "file": ""}
            )
            st.session_state.batch_last_event = (
                f"❌ Loi [{batch_idx+1}/{len(keywords)}]: {keyword} bi chan boi worker preflight."
            )

    except Exception as exc:
        _dl.error("[BATCH] Exception processing '%s': %s", keyword, exc)
        st.session_state.batch_results.append(
            {"keyword": keyword, "status": f"error: {exc}", "file": ""}
        )
        st.session_state.batch_last_event = f"Loi [{batch_idx+1}/{len(keywords)}]: {exc}"

    # Move to next keyword or finish
    st.session_state.batch_idx = batch_idx + 1
    if st.session_state.batch_idx < len(keywords):
        st.rerun()
    else:
        st.session_state.batch_running = False
        st.session_state.batch_current_keyword = ""
        st.session_state.batch_last_event = (
            f"DA XONG! {len(st.session_state.batch_results)}/{len(keywords)} keywords xu ly xong."
        )


def render_hero(active_project, worker_running: bool, metrics: dict) -> None:
    mode_label = "Cloud" if IS_CLOUD else "Local"
    project_label = active_project.brand_name if active_project else "Chưa chọn project"
    worker_label = "Đang chạy" if worker_running or st.session_state.batch_running else "Sẵn sàng"
    active_pipeline = "Queue đang chạy" if worker_running or st.session_state.batch_running else "Chưa có batch active"
    st.markdown(
        f"""
        <div class="hero-shell">
            <div class="hero-kicker">Semantic SEO Workflow</div>
            <div class="hero-title">Content Brief Generator</div>
            <div class="hero-copy">
                Tạo content brief theo hướng Semantic SEO, theo dõi queue xử lý theo thời gian thực và quản lý
                project context trong một luồng vận hành rõ ràng hơn thay vì trải trên nhiều panel rời rạc.
            </div>
            <div class="pill-row">
                <div class="pill">Chế độ: <strong>{mode_label}</strong></div>
                <div class="pill">Project: <strong>{project_label}</strong></div>
                <div class="pill">Tiến trình: <strong>{worker_label}</strong></div>
                <div class="pill">Bản ghi: <strong>{metrics["total"]}</strong></div>
                <div class="pill">Version: <strong>{BUILD_VERSION}</strong></div>
            </div>
            <div class="status-strip">
                <div class="status-card">
                    <strong>Trung tâm điều khiển</strong>
                    <span>Tab đầu dành cho nhập keyword, chọn module và khởi chạy batch. Các khu còn lại phục vụ theo dõi, quản trị project và tích hợp.</span>
                </div>
                <div class="status-card">
                    <strong>Trạng thái hiện tại</strong>
                    <span>{active_pipeline}. Worker local và cloud batch đều được phản ánh lại ở các panel chạy job phía dưới.</span>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_generate_snapshot(
    *,
    active_project,
    keywords: list[str],
    input_method: str,
    enable_serp: bool,
    enable_network: bool,
    enable_context: bool,
    enable_linking: bool,
    methodology: str,
    sheet_url: str,
) -> None:
    project_label = active_project.brand_name if active_project else "No active project"
    enabled_modules = sum([enable_serp, enable_network, enable_context, enable_linking])
    module_label = ", ".join(
        name
        for name, enabled in [
            ("SERP", enable_serp),
            ("Network", enable_network),
            ("Context", enable_context),
            ("Linking", enable_linking),
        ]
        if enabled
    ) or "No module enabled"
    target_sheet = sheet_url or DEFAULT_SHEET_URL
    st.markdown(
        f"""
        <div class="deck-grid">
            <div class="deck-card deck-card-tint">
                <span class="deck-eyebrow">Batch Input</span>
                <div class="deck-value">{len(keywords)} keyword</div>
                <div class="deck-meta">Nguồn: {input_method}. Project: {project_label}.</div>
            </div>
            <div class="deck-card">
                <span class="deck-eyebrow">Pipeline</span>
                <div class="deck-value">{enabled_modules}/4 module</div>
                <div class="deck-meta">{module_label}</div>
            </div>
            <div class="deck-card">
                <span class="deck-eyebrow">Methodology</span>
                <div class="deck-value">{METHODOLOGY_LABELS.get(methodology, methodology)}</div>
                <div class="deck-meta">Áp dụng cho brief hiện tại.</div>
            </div>
            <div class="deck-card">
                <span class="deck-eyebrow">Output Destination</span>
                <div class="deck-value">Google Sheet</div>
                <div class="deck-meta">{target_sheet}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar(active_project, worker_running: bool, metrics: dict) -> None:
    with st.sidebar:
        st.markdown("### Điều hướng nhanh")
        st.caption("Ưu tiên thao tác trong các tab bên dưới. Sidebar chỉ giữ phần tổng quan.")
        st.metric("Chế độ", "Cloud" if IS_CLOUD else "Local")
        st.metric("Version", BUILD_VERSION)
        # Phase 3.4: Add Running metric + 3-state color-coded status
        if worker_running:
            status_label = "🟢 Worker local đang chạy"
        elif st.session_state.batch_running:
            status_label = "🔵 Cloud batch đang xử lý"
        else:
            status_label = "⚪ Rảnh"
        st.metric("Trạng thái", status_label)
        st.metric("Done", metrics["done"])
        st.metric("Running", metrics["running"])   # Phase 3.4: was missing
        st.metric("Error", metrics["error"])

        if active_project:
            st.markdown("### Project đang dùng")
            st.write(f"**{active_project.brand_name}**")
            st.caption(active_project.domain)
        else:
            st.info("Chưa chọn project active.")

        if IS_CLOUD:
            st.warning("Streamlit Cloud xử lý tuần tự trong cùng phiên chạy. Batch lớn nên dùng local.")


def render_generate_tab(active_project, worker_running: bool) -> str:
    # Prime runtime keys before any key-status UI is rendered.
    key_dbg = _sync_api_keys_to_env()
    st.markdown(
        """
        <div class="panel-note">
            <h4>Control Deck</h4>
            <p>Nhập keyword ở cột trái, kiểm tra readiness ở cột phải, rồi mới chạy batch. Settings chi tiết vẫn nằm ở tab Cài đặt để khu thao tác chính gọn và ít nhiễu hơn.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.write("")

    col_input, col_run = st.columns([1.1, 0.9], gap="large")
    sheet_url = ""
    keywords: list[str] = []

    with col_input:
        with st.container(border=True):
            st.markdown("##### 1. Keyword Intake")
            st.markdown('<div class="section-kicker">Input Zone</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="section-copy">Nạp batch keyword và kiểm tra nhanh chất lượng đầu vào trước khi chạy pipeline.</div>',
                unsafe_allow_html=True,
            )
            if active_project:
                st.caption(f"Project active: {active_project.brand_name} · {active_project.domain}")
            else:
                st.caption("Chưa có project active. Brief vẫn chạy nhưng thiếu source context cho brand.")
            input_method = st.radio(
                "Nguồn dữ liệu",
                options=["Nhập thủ công", "Upload CSV"],
                horizontal=True,
            )

            if input_method == "Nhập thủ công":
                kw_text = st.text_area(
                    "Keyword list",
                    height=220,
                    placeholder="khái niệm A là gì\nchi phí dịch vụ B bao nhiêu\ncách chọn sản phẩm C phù hợp",
                )
                keywords = [item.strip() for item in kw_text.splitlines() if item.strip()]
            else:
                uploaded_csv = st.file_uploader("Tải lên file CSV", type=["csv"], key="keyword_csv")
                if uploaded_csv is not None:
                    keywords, csv_error = normalize_uploaded_keywords(uploaded_csv)
                    if csv_error:
                        st.error(csv_error)

            st.metric("Số keyword hợp lệ", len(keywords))
            duplicate_count = len(keywords) - len(set(keywords))
            if duplicate_count > 0:
                st.info(f"Có {duplicate_count} keyword trùng trong batch hiện tại. Mỗi lần chạy vẫn được ghi riêng trên Google Sheet.")
            if keywords:
                with st.expander("Xem trước keyword", expanded=False):
                    preview_df = pd.DataFrame({"Keyword": keywords[:100]})
                    st.dataframe(preview_df, use_container_width=True, hide_index=True)

        st.write("")
        with st.container(border=True):
            st.markdown("##### 2. Pipeline Setup")
            st.markdown('<div class="section-kicker">Execution Scope</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="section-copy">Chọn đúng module cần dùng cho batch này. Không nên bật mọi thứ theo quán tính nếu mục tiêu chỉ là brief chuẩn outline-content.</div>',
                unsafe_allow_html=True,
            )
            settings_col1, settings_col2 = st.columns(2)
            with settings_col1:
                # Phase 3.3: Tooltips cho pipeline checkboxes
                enable_serp = st.checkbox(
                    "🔍 SERP + Phân tích đối thủ",
                    value=True,
                    help="Bật: crawl Google SERP + phân tích HTML top đối thủ để trích xuất heading, n-gram, content gaps.",
                )
                enable_network = st.checkbox(
                    "🌐 Semantic Query Network",
                    value=True,
                    help="Bật: LLM cluster keywords xung quanh central entity → xây dựng topical map cho website.",
                )
            with settings_col2:
                enable_context = st.checkbox(
                    "📋 Context Builder",
                    value=False,
                    help="Bật: LLM sinh Context Vectors + Structure Outline từ dữ liệu đối thủ (cần SERP bật trước).",
                )
                enable_linking = st.checkbox(
                    "🔗 Internal Linking",
                    value=True,
                    help="Bật: gợi ý internal links từ topical map — tăng crawl budget và topical authority.",
                )

            methodology = st.selectbox(
                "Methodology",
                options=list(METHODOLOGY_LABELS.keys()),
                format_func=lambda key: METHODOLOGY_LABELS.get(key, key),
            )
            st.caption("Checklist: keyword có dữ liệu, API keys đủ, project active đúng brand, và SERP chỉ bật khi có Serper.")

    with col_run:
        with st.container(border=True):
            st.markdown("##### 3. Run Console")
            st.markdown('<div class="section-kicker">Readiness & Dispatch</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="section-copy">Kiểm tra nguồn key, project đang áp dụng và đích ghi log trước khi dispatch job.</div>',
                unsafe_allow_html=True,
            )
            sheet_url = st.text_input(
                "Google Sheet URL",
                value=DEFAULT_SHEET_URL,
                help="Có thể để mặc định nếu đang dùng sheet cũ.",
            )

            openai_ready = "Có" if _api_key("OPENAI_API_KEY") else "Thiếu"
            serper_ready = "Có" if _api_key("SERPER_API_KEY") else "Thiếu"
            openai_source = _resolve_api_key_info("OPENAI_API_KEY")[1]
            serper_source = _resolve_api_key_info("SERPER_API_KEY")[1]
            project_ready = active_project.brand_name if active_project else "Chưa chọn"

            stat1, stat2 = st.columns(2)
            stat1.metric("OpenAI", openai_ready)
            stat2.metric("Serper", serper_ready)
            status_message = "Google via Serper.dev" if serper_ready == "Có" else "Fallback sẽ kém tin cậy hơn"
            st.markdown(
                f"""
                <div class="deck-grid">
                    <div class="deck-card">
                        <span class="deck-eyebrow">Project</span>
                        <div class="deck-value">{project_ready}</div>
                        <div class="deck-meta">Brand context được inject vào prompt nếu project đang active.</div>
                    </div>
                    <div class="deck-card">
                        <span class="deck-eyebrow">SERP Source</span>
                        <div class="deck-value">{status_message}</div>
                        <div class="deck-meta">Nguồn chuẩn cho Google results là Serper.dev. HTML/DDG chỉ là fallback.</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption("Khi chạy lại cùng một keyword, app sẽ cập nhật lại chính dòng cũ trên Google Sheet để bạn dễ theo dõi.")
            st.caption(f"Key source: OpenAI={openai_source}, Serper={serper_source}")
            if key_dbg.get("llm_config_updated"):
                st.caption(
                    f"Runtime key sync: OpenAI={key_dbg.get('openai_source', 'missing')}, "
                    f"Serper={key_dbg.get('serper_source', 'missing')}"
                )
            st.caption("Outline-content mode: dùng SERP/PAA/related-search/competitor headings nội bộ; bỏ qua volume/KD provider config.")
            st.caption(f"Version đang chạy: `{BUILD_VERSION}`")

            run_issues = validate_run_request(keywords, enable_serp)
            if run_issues:
                for issue in run_issues:
                    st.warning(issue)

            action_col1, action_col2, action_col3 = st.columns([1.5, 1.2, 1])
            with action_col1:
                start_batch = st.button(
                    "Chạy batch",
                    type="primary",
                    use_container_width=True,
                    disabled=bool(run_issues) or worker_running,
                )
            with action_col2:
                refresh = st.button("Làm mới", use_container_width=True)
            with action_col3:
                stop_batch = st.button(
                    "Dừng",
                    use_container_width=True,
                    disabled=not worker_running and not st.session_state.batch_running,
                )

            # Phase 35: "Làm mới" phải dùng form submit để tránh bị skip khi auto-rerun
            # Nếu refresh thì chỉ rerun, không chạy logic bên dưới
            if refresh:
                st.rerun()
                return  # Exit sớm — rerun đã trigger rồi

            # Phase 35: Auto-poll sau khi khởi động worker
            # Sau rerun, worker đã start rồi → poll 5 lần mỗi 2 giây để xác nhận worker alive
            if start_batch:
                job_data = build_job_payload(
                    keywords=keywords,
                    sheet_url=sheet_url,
                    enable_serp=enable_serp,
                    enable_network=enable_network,
                    enable_context=enable_context,
                    enable_linking=enable_linking,
                    methodology=methodology,
                    active_project=active_project,
                )
                write_job_payload(job_data)

                if IS_CLOUD:
                    queue_cloud_batch(job_data)
                    st.success("Đã khởi tạo cloud batch. Hệ thống sẽ chạy tuần tự từng keyword.")
                    st.rerun()
                else:
                    start_local_worker()
                    st.success("Đã khởi chạy worker nền. Đang xác nhận worker alive...")

                    # Phase 35: Poll 5 lần x 2 giây để xác nhận worker thực sự chạy
                    # Sau rerun, lock file đã có PID thật → đọc và kiểm tra
                    poll_ok = False
                    for _poll_round in range(5):
                        time.sleep(2)
                        if os.path.exists(LOCK_FILE):
                            with open(LOCK_FILE, "r", encoding="utf-8", errors="ignore") as _lf:
                                _pid_str = _lf.read().strip()
                            if _pid_str.isdigit():
                                _pid = int(_pid_str)
                                # Đọc log mới nhất để xác nhận worker đã bắt đầu
                                _log_lines = []
                                if os.path.exists(ERROR_LOG_PATH):
                                    try:
                                        with open(ERROR_LOG_PATH, "r", encoding="utf-8", errors="replace") as _lf2:
                                            _log_lines = _lf2.readlines()
                                        # Worker log luôn bắt đầu bằng dòng "WORKER BẮT ĐẦU"
                                        if any("WORKER BẮT ĐẦU" in l for l in _log_lines[-20:]):
                                            poll_ok = True
                                            st.success(f"Worker PID={_pid} đã khởi động thành công.")
                                            break
                                    except Exception:
                                        pass

                    if not poll_ok:
                        st.warning("Worker đã khởi động nhưng chưa xác nhận được log. Nhấn 'Làm mới' để kiểm tra lại.")
                    st.rerun()

            if stop_batch:
                if IS_CLOUD:
                    st.session_state.batch_running = False
                    st.session_state.batch_current_keyword = ""
                    st.session_state.batch_last_event = "Đã dừng cloud batch."
                else:
                    stop_local_worker()
                st.rerun()

            total_batch = len(st.session_state.batch_keywords)
            current_idx = st.session_state.batch_idx
            # Phase 36: Chỉ hiện progress bar khi thực sự có batch đang chạy
            # worker_running=True nhưng total_batch=0 → không hiện progress (worker idle/finished)
            has_active_work = (st.session_state.batch_running and total_batch > 0) or worker_running
            if has_active_work:
                progress = current_idx / total_batch if total_batch > 0 else 0.0
                st.progress(progress)
                # Phase 3.3: Hiện step + keyword đang xử lý
                step_label = f"[{current_idx}/{total_batch}] {st.session_state.batch_current_keyword or 'Đang chuẩn bị...'}"
                st.caption(step_label)

            if st.session_state.batch_running and IS_CLOUD:
                current_kw = st.session_state.batch_current_keyword or "Đang chuẩn bị keyword tiếp theo"
                st.info(f"Cloud đang xử lý: **{current_kw}**")
            elif worker_running:
                st.info("Worker local đang chạy nền. Xem log ở phần dưới.")
            else:
                st.caption("Chưa có batch nào đang chạy.")

            if st.session_state.batch_last_event:
                st.caption(st.session_state.batch_last_event)

        st.write("")
        with st.container(border=True):
            st.markdown("##### 4. Runtime Log")
            st.markdown('<div class="section-kicker">Execution Trace</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="section-copy">Theo dõi trạng thái worker, lỗi gần nhất và tín hiệu batch mà không phải rời khỏi màn hình thao tác.</div>',
                unsafe_allow_html=True,
            )
            log_tail = read_log_tail(ERROR_LOG_PATH)
            if log_tail:
                st.code(log_tail, language="text")
            elif st.session_state.batch_results:
                st.code(
                    "\n".join(
                        f"{item['keyword']}: {item['status']}" for item in st.session_state.batch_results[-12:]
                    ),
                    language="text",
                )
            else:
                st.caption("Chưa có log mới.")

    render_generate_snapshot(
        active_project=active_project,
        keywords=keywords,
        input_method=input_method,
        enable_serp=enable_serp,
        enable_network=enable_network,
        enable_context=enable_context,
        enable_linking=enable_linking,
        methodology=methodology,
        sheet_url=sheet_url,
    )

    return sheet_url


def render_results_tab(df_db: pd.DataFrame) -> None:
    st.subheader("Kết quả & theo dõi")
    st.caption("Tra cứu batch đã chạy, lọc nhanh theo keyword/trạng thái và mở brief chi tiết ngay trong app.")

    metrics = compute_status_metrics(df_db)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Tổng bản ghi", metrics["total"])
    m2.metric("Done", metrics["done"])
    m3.metric("Running", metrics["running"])
    m4.metric("Error", metrics["error"])

    if df_db.empty:
        # Phase 1.6 fix: Empty state với CTA
        st.info("Chưa có dữ liệu trong database.")
        st.caption("👉 Vào tab **'Tạo brief'** để chạy batch đầu tiên, hoặc upload file CSV keyword.")
        if st.session_state.batch_results:
            st.dataframe(pd.DataFrame(st.session_state.batch_results), use_container_width=True, hide_index=True)
        return

    # Phase 1.6: Search + filter controls
    filter_col1, filter_col2 = st.columns([2, 1])
    with filter_col1:
        search_term = st.text_input(
            "🔍 Tìm keyword...",
            placeholder="VD: keyword chính, nhóm chủ đề,...",
            key="result_search",
        )
    with filter_col2:
        status_options = ["Tất cả", "Done", "Running", "Error"]
        status_filter = st.selectbox("Lọc trạng thái", status_options, key="result_status_filter")

    # Apply filters
    filtered_df = df_db.copy()
    if search_term:
        filtered_df = filtered_df[
            filtered_df["Keyword"].str.contains(search_term, case=False, na=False)
        ]
    if status_filter != "Tất cả":
        filtered_df = filtered_df[
            filtered_df["Trạng thái"].str.contains(status_filter, case=False, na=False)
        ]

    st.caption(f"Hiển thị {len(filtered_df)} / {len(df_db)} bản ghi")
    display_df = filtered_df.drop(
        columns=[
            "Full Content Brief",
            "Macro Context",
            "EAV Table",
            "FS/PAA Map",
            "Source Context Alignment",
            "Koray Quality Score",
        ],
        errors="ignore",
    )
    st.dataframe(display_df, use_container_width=True, height=360)

    # Phase 1.6 fix: Precompute label_map to avoid O(n) df.at[] on every render
    options = list(reversed(filtered_df.index.tolist()))
    label_map = {
        idx: f"{filtered_df.at[idx, 'Keyword']} | {filtered_df.at[idx, 'Trạng thái']}"
        for idx in options
    }
    selected_idx = st.selectbox(
        "Chọn bản ghi để xem chi tiết",
        options=options,
        format_func=lambda idx: label_map.get(idx, "—"),
    )
    selected_row = filtered_df.loc[selected_idx]

    detail_tabs = st.tabs(["Brief", "Koray", "Tóm tắt"])

    with detail_tabs[0]:
        content = str(selected_row.get("Full Content Brief", "") or "")
        if content and content != "nan":
            # Phase 3.5: Add export action buttons
            action_cols = st.columns([1, 1])
            with action_cols[0]:
                st.download_button(
                    "📥 Download .md",
                    data=content.encode("utf-8"),
                    file_name=f"brief_{selected_row.get('Keyword', 'untitled')}.md",
                    mime="text/markdown",
                    use_container_width=True,
                    key="dl_brief_btn",
                )
            st.markdown("---")
            st.markdown(content)
        else:
            st.info("Bản ghi này chưa có brief.")

    with detail_tabs[1]:
        koray_fields = [
            "Macro Context",
            "EAV Table",
            "FS/PAA Map",
            "Source Context Alignment",
            "Koray Quality Score",
        ]
        found = False
        for field in koray_fields:
            value = str(selected_row.get(field, "") or "")
            if value and value != "nan":
                found = True
                with st.expander(field, expanded=False):
                    st.markdown(value)
        if not found:
            st.info("Chưa có dữ liệu Koray cho bản ghi này.")

    with detail_tabs[2]:
        quick = {
            "Keyword": selected_row.get("Keyword", ""),
            "Trạng thái": selected_row.get("Trạng thái", ""),
            "Intent": selected_row.get("Search Intent", ""),
            "Top đối thủ": selected_row.get("Top 10 Đối thủ", selected_row.get("Top 3 Đối thủ", "")),
            "Internal Links": selected_row.get("Internal Links", ""),
        }
        st.json(quick)


def render_project_form(pm: ProjectManager) -> None:
    """
    Phase 3.1: Project form dùng st.dialog() (Streamlit 1.32+)
    với 3 tab để giảm phức tạp (17 fields → 3 groups).
    """
    # Use st.dialog for clean modal (available in Streamlit 1.27+)
    try:
        _dialog = st.dialog
    except AttributeError:
        # Fallback: dùng st.form cho Streamlit cũ hơn
        _dialog = None

    edit_id = st.session_state.get("edit_project_id")
    project = pm.get_by_id(edit_id) if edit_id else None
    values = project_to_dict(project)
    title = f"Sửa project: {project.name}" if project else "Tạo project mới"

    if _dialog is not None:
        with _dialog(title, width="large"):
            _render_project_form_body(pm, edit_id, values, title)
    else:
        with st.container(border=True):
            st.subheader(title)
            _render_project_form_body(pm, edit_id, values, title)


def _render_project_form_body(pm: ProjectManager, edit_id, values: dict, title: str) -> None:
    """Helper: nội dung form project — dùng chung cho dialog và container fallback."""
    st.caption("Các trường đánh dấu * là bắt buộc. Tab 1 → 2 → 3 rồi Lưu.")
    # Phase 3.1: 3-tab layout (không dùng st.form trong dialog để tránh conflict)
    tab1, tab2, tab3 = st.tabs([
        "📋 Thông tin cơ bản",
        "🏷️ Thương hiệu & Tone",
        "📍 NAP & Địa điểm",
    ])

    with tab1:
        st.markdown("**Thông tin nhận diện**")
        name = st.text_input("Tên project *", value=values["name"])
        brand_name = st.text_input("Brand name *", value=values["brand_name"])
        domain = st.text_input("Domain *", value=values["domain"], placeholder="example.com")
        company_full_name = st.text_input("Tên công ty đầy đủ", value=values["company_full_name"])
        industry = st.text_input("Ngành / lĩnh vực", value=values["industry"])

        st.markdown("**Sản phẩm & Khách hàng**")
        main_products = st.text_area(
            "Sản phẩm chính *",
            value=values["main_products"],
            height=100,
            placeholder="Mỗi dòng 1 sản phẩm hoặc 1 nhóm sản phẩm",
        )
        target_customers = st.text_input("Khách hàng mục tiêu", value=values["target_customers"])

    with tab2:
        st.markdown("**Định vị thương hiệu**")
        usp = st.text_area("USP / Lợi thế cạnh tranh *", value=values["usp"], height=90)
        tone = st.text_input("Tone & giọng văn", value=values["tone"])
        competitor_brands = st.text_area(
            "Brand đối thủ (không đặt làm H2 độc lập)",
            value=values["competitor_brands"],
            height=70,
            help="Liệt kê tên brand đối thủ cạnh tranh — hệ thống sẽ tránh đặt chúng làm H2 Main trong brief.",
        )
        technical_standards = st.text_input(
            "Tiêu chuẩn kỹ thuật",
            value=values["technical_standards"],
            placeholder="VD: tiêu chuẩn ngành, quy định, chứng nhận, guideline nội bộ...",
        )

    with tab3:
        st.markdown("**Thông tin liên hệ (NAP)**")
        col_nap1, col_nap2 = st.columns(2)
        with col_nap1:
            hotline = st.text_input("Hotline / Zalo", value=values["hotline"])
            email = st.text_input("Email", value=values["email"])
        with col_nap2:
            address = st.text_input("Địa chỉ trụ sở", value=values["address"])
            warehouse = st.text_input("Kho / Chi nhánh", value=values["warehouse"])
        geo_keywords = st.text_input(
            "GEO keywords",
            value=values["geo_keywords"],
            placeholder="VD: Hà Nội, Miền Bắc, Đông Nam Bộ",
            help="Các từ khóa địa lý mà brand phục vụ — ảnh hưởng đến nội dung brief.",
        )
        topical_map_csv = st.text_input(
            "📁 Đường dẫn Topical Map CSV *",
            value=values.get("topical_map_csv", ""),
            placeholder="VD: projects/my_project_topics.csv",
            help=(
                "File CSV chứa danh sách bài viết trong Topical Map của project này. "
                "Cột 1 = Keyword bài viết. NẾU ĐỂ TRỐNG → Hệ thống gợi ý bài nhầm NGÀNH "
                "(ví dụ: bài thuộc ngành này nhận gợi ý từ ngành khác). "
                "Bắt buộc phải có với mỗi project."
            ),
        )
        if not topical_map_csv.strip():
            st.error("⚠️ Topical Map CSV là BẮT BUỘC — để trống sẽ gây nhầm lẫn bài viết giữa các ngành.")

    st.markdown("---")
    action1, action2 = st.columns([1.4, 1])
    save_project = action1.button("💾 Lưu project", type="primary", use_container_width=True)
    cancel_project = action2.button("Hủy", use_container_width=True)

    if cancel_project:
        st.session_state.show_project_form = False
        st.session_state.edit_project_id = None
        st.rerun()

    if save_project:
        if not name.strip() or not brand_name.strip() or not domain.strip() or not main_products.strip():
            st.error("Cần điền đủ: Tên project, Brand name, Domain và Sản phẩm chính.")
        elif not topical_map_csv.strip():
            st.error("⚠️ Topical Map CSV là BẮT BUỘC. Vui lòng nhập đường dẫn file CSV chứa danh sách bài viết của project.")
        else:
            payload = {
                "name": name.strip(),
                "brand_name": brand_name.strip(),
                "domain": domain.strip(),
                "company_full_name": company_full_name.strip(),
                "industry": industry.strip(),
                "main_products": main_products.strip(),
                "usp": usp.strip(),
                "target_customers": target_customers.strip(),
                "competitor_brands": competitor_brands.strip(),
                "tone": tone.strip(),
                "technical_standards": technical_standards.strip(),
                "topical_map_csv": topical_map_csv.strip(),
                "geo_keywords": geo_keywords.strip(),
                "hotline": hotline.strip(),
                "email": email.strip(),
                "address": address.strip(),
                "warehouse": warehouse.strip(),
            }
            if edit_id:
                pm.update(edit_id, payload)
                st.success("Đã cập nhật project.")
            else:
                pm.create(payload)
                st.success("Đã tạo project mới.")
            st.session_state.show_project_form = False
            st.session_state.edit_project_id = None
            st.rerun()


def render_projects_tab(pm: ProjectManager, active_project) -> None:
    st.subheader("Project & source context")
    st.caption("Quản lý brand context, topical map và project active đang được inject vào pipeline.")
    projects = pm.get_all()

    summary_col1, summary_col2 = st.columns([1, 1])
    with summary_col1:
        with st.container(border=True):
            st.markdown("#### Project đang active")
            if active_project:
                st.write(f"**{active_project.brand_name}**")
                st.caption(active_project.domain)
                st.write(active_project.industry or "Chưa khai báo ngành.")
            else:
                st.info("Chưa có project active.")
    with summary_col2:
        with st.container(border=True):
            st.markdown("#### Tác vụ nhanh")
            if st.button("Tạo project mới", use_container_width=True):
                st.session_state.show_project_form = True
                st.session_state.edit_project_id = None
                st.rerun()

    if projects:
        selected_pid = st.selectbox(
            "Danh sách project",
            options=[project.id for project in projects],
            format_func=lambda pid: next(
                f"[{project.id}] {project.name} · {project.domain}"
                for project in projects
                if project.id == pid
            ),
        )

        btn1, btn2, btn3 = st.columns(3)
        if btn1.button("Set active", use_container_width=True):
            pm.set_active(selected_pid)
            st.rerun()
        if btn2.button("Sửa project", use_container_width=True):
            st.session_state.show_project_form = True
            st.session_state.edit_project_id = selected_pid
            st.rerun()
        if btn3.button("Xóa project", use_container_width=True):
            st.session_state.confirm_delete_pid = selected_pid

        if st.session_state.get("confirm_delete_pid"):
            project_to_delete = pm.get_by_id(st.session_state.confirm_delete_pid)
            label = project_to_delete.name if project_to_delete else f"ID={st.session_state.confirm_delete_pid}"
            st.warning(f"Bạn sắp xóa project `{label}`.")
            confirm_col1, confirm_col2 = st.columns(2)
            if confirm_col1.button("Hủy xóa", use_container_width=True):
                st.session_state.confirm_delete_pid = None
                st.rerun()
            if confirm_col2.button("Xác nhận xóa", type="primary", use_container_width=True):
                pm.delete(st.session_state.confirm_delete_pid)
                st.session_state.confirm_delete_pid = None
                st.rerun()

        project_rows = [
            {
                "ID": project.id,
                "Project": project.name,
                "Brand": project.brand_name,
                "Domain": project.domain,
                "Industry": project.industry,
                "Active": "Yes" if project.is_active else "",
            }
            for project in projects
        ]
        st.dataframe(pd.DataFrame(project_rows), use_container_width=True, hide_index=True)

        selected_project = pm.get_by_id(selected_pid)
        if selected_project:
            with st.container(border=True):
                st.markdown("#### Source Context Preview")
                st.caption("Khối này là ngữ cảnh thương hiệu được inject vào prompt khi pipeline chạy.")
                st.code(pm.to_source_context_string(selected_project), language="markdown")
    else:
        st.info("Chưa có project nào.")

    if st.session_state.show_project_form:
        render_project_form(pm)


def render_settings_tab(sheet_url: str) -> None:
    st.subheader("Cài đặt hệ thống")
    st.caption("Khối này dành cho tích hợp và bảo trì. Tác vụ chạy brief hàng ngày nên thực hiện ở tab đầu.")
    left, right = st.columns([1, 1], gap="large")

    with left:
        with st.container(border=True):
            st.markdown("#### API keys")
            st.caption("Lưu vào `.env` để worker local và app dùng lại được ở lần chạy sau.")
            with st.form("api_form"):
                serper_key = st.text_input(
                    "Serper API Key",
                    value=_api_key("SERPER_API_KEY"),
                    type="password",
                )
                openai_key = st.text_input(
                    "OpenAI API Key",
                    value=_api_key("OPENAI_API_KEY"),
                    type="password",
                )
                st.caption("Tool hiện chạy theo logic outline-content nội bộ; volume/KD provider được bỏ qua khỏi cấu hình.")
                submitted = st.form_submit_button("Lưu API keys", type="primary", use_container_width=True)

            # Phase 36: Hiện success message BÊN NGOÀI form để không bị form re-render xóa
            if submitted:
                msg = save_api_keys(serper_key, openai_key)
                st.session_state["settings_success"] = msg

    # Hiện message BÊN NGOÀI form (sau form đã submit)
    if "settings_success" in st.session_state:
        st.success(st.session_state.pop("settings_success"))

    with right:
        with st.container(border=True):
            st.markdown("#### Google Sheets")
            st.caption("Dùng để đồng bộ tiến trình pipeline theo thời gian thực.")
            st.text_input("Credentials path", value=CREDS_PATH, disabled=True)
            uploaded_creds = st.file_uploader(
                "Upload service account JSON (local only)",
                type=["json"],
                key="settings_creds",
            )
            if uploaded_creds is not None:
                result = save_credentials_file(uploaded_creds)
                if result.startswith("Đã lưu"):
                    st.session_state["settings_success"] = result
                    st.session_state["uploaded_creds_path"] = CREDS_PATH
                else:
                    st.session_state["settings_error"] = result

        # Phase 39 Fix: Hướng dẫn Streamlit Cloud Secrets (PERSISTENT)
        with st.container(border=True):
            st.markdown("#### ☁️ Streamlit Cloud Secrets (quan trọng!)")
            st.caption(
                "Điền vào **Settings → Secrets** trên Streamlit Cloud để API keys + "
                "credentials PERSIST qua mỗi lần redeploy."
            )
            with st.expander("📋 Hướng dẫn cài đặt Cloud Secrets (chỉ làm 1 lần)", expanded=False):
                st.markdown("""
                **Trên Streamlit Cloud — Settings → Secrets, dán:**

                ```toml
                OPENAI_API_KEY = "sk-proj-YOUR_OPENAI_KEY_HERE"
                SERPER_API_KEY = "YOUR_SERPER_KEY_HERE"
                sheet_url = "https://docs.google.com/spreadsheets/d/YOUR_SHEET_ID"
                ```

                **Service Account Credentials:**
                Dán nội dung file JSON vào ô `gsheet_credentials` bên dưới (hoặc paste trực tiếp vào Secrets dashboard).
                Sau khi lưu → **Secrets PERSIST qua mỗi lần redeploy.**
                """)
            # Hiển thị trạng thái Secrets hiện tại
            _creds_data, _creds_path, _creds_source = _get_valid_gsheet_creds_with_source()
            test_col, status_col = st.columns([1, 2])
            with test_col:
                if st.button("🔗 Test kết nối GSheet", use_container_width=True):
                    ok, msg = test_gsheet_connection(sheet_url)
                    if ok:
                        st.session_state["settings_success"] = msg
                    else:
                        st.session_state["settings_error"] = msg
            with status_col:
                if _creds_data:
                    email = _creds_data.get("client_email", "?")
                    st.caption(f"✅ Credentials dict ({_creds_source}): {email}")
                elif _creds_path:
                    st.caption(f"✅ Credentials file ({_creds_source}): {os.path.basename(_creds_path)}")
                else:
                    st.caption("⚠️ Chưa có credentials.")

    # Hiện message sau test
    if "settings_success" in st.session_state:
        st.success(st.session_state.pop("settings_success"))
    if "settings_error" in st.session_state:
        st.error(st.session_state.pop("settings_error"))

    st.write("")
    with st.container(border=True):
        st.markdown("#### Bảo trì dữ liệu")
        st.caption("Reset CSV local và xóa dữ liệu cũ trên Google Sheet từ dòng 2 trở đi.")
        # Phase 1.7: Confirmation dialog trước khi reset (2-step confirm)
        if "confirm_reset" not in st.session_state:
            st.session_state.confirm_reset = False

        if not st.session_state.confirm_reset:
            if st.button("⚠️ Reset database", type="primary"):
                st.session_state.confirm_reset = True
                st.rerun()
        else:
            st.warning("⚠️ Bạn sắp xóa toàn bộ dữ liệu CSV và Google Sheet. Hành động này KHÔNG THỂ HOÀN TÁC.")
            warn_col1, warn_col2 = st.columns(2)
            if warn_col1.button("Hủy", use_container_width=True):
                st.session_state.confirm_reset = False
                st.rerun()
            if warn_col2.button("🗑️ Xác nhận xóa toàn bộ", type="primary", use_container_width=True):
                for message in reset_database(sheet_url):
                    if "lỗi" in message.lower() or "không" in message.lower():
                        st.warning(message)
                    else:
                        st.success(message)
                st.session_state.confirm_reset = False

    with st.container(border=True):
        st.markdown("#### Ghi chú vận hành")
        st.write("Cloud mode xử lý tuần tự và phù hợp batch nhỏ.")
        st.write("Local worker vẫn là lựa chọn ổn hơn khi chạy nhiều keyword hoặc debug pipeline.")
        st.write("Secrets nên ưu tiên cấu hình ở Streamlit Secrets khi chạy cloud lâu dài.")


inject_ui_css()
init_state()
process_cloud_batch_if_needed()

pm = ProjectManager()
active_project = pm.get_active()
df_db = load_database()
metrics = compute_status_metrics(df_db)
worker_running = os.path.exists(LOCK_FILE)

render_sidebar(active_project, worker_running, metrics)
render_hero(active_project, worker_running, metrics)

tab_generate, tab_results, tab_projects, tab_settings = st.tabs(
    ["⚡ Tạo brief", "📊 Kết quả", "🗂 Projects", "🔧 Cài đặt"]
)

with tab_generate:
    current_sheet_url = render_generate_tab(active_project, worker_running)

with tab_results:
    render_results_tab(df_db)

with tab_projects:
    render_projects_tab(pm, active_project)

with tab_settings:
    render_settings_tab(current_sheet_url)
