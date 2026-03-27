import json
import os
import subprocess
import sys
import time

import pandas as pd
import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
except ImportError:
    pass

from modules.article_writer import METHODOLOGY_LABELS
from modules.gsheet_logger import GSheetLogger
from modules.project_manager import ProjectManager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")
CREDS_PATH = os.path.join(BASE_DIR, "gen-lang-client-0396271616-70425b3ad4fb.json")
DB_PATH = os.path.join(BASE_DIR, "database_v2.csv")
JOB_FILE = os.path.join(BASE_DIR, "job_queue.json")
LOCK_FILE = os.path.join(BASE_DIR, "worker_lock.txt")
ERROR_LOG_PATH = os.path.join(BASE_DIR, "worker_error.log")
DEFAULT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1i_lgFmoB1LJq2Lt01CwDlOk3hVbQxPiZ4LqGqf8mgwM"

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
        :root {
            --bg: #e9eef5;
            --panel: #eef3f9;
            --panel-2: #e3eaf3;
            --ink: #203047;
            --muted: #5f7088;
            --accent: #4f7df3;
            --accent-2: #79c4b7;
            --ok: #3faa72;
            --danger: #d96a79;
            --line: rgba(131, 146, 171, 0.20);
            --shadow-hi: rgba(255, 255, 255, 0.95);
            --shadow-lo: rgba(160, 174, 194, 0.65);
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(79, 125, 243, 0.10), transparent 28%),
                radial-gradient(circle at top right, rgba(121, 196, 183, 0.12), transparent 24%),
                linear-gradient(180deg, #edf2f8 0%, #e6ecf4 100%);
            color: var(--ink);
        }
        .block-container {
            padding-top: 2rem;
            padding-bottom: 2rem;
        }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #e9eef5 0%, #e3eaf3 100%);
            border-right: 1px solid var(--line);
        }
        div[data-testid="stTabs"] button {
            border-radius: 999px;
            padding: 0.5rem 1rem;
            background: var(--panel);
            color: var(--muted);
            border: 0;
            box-shadow: 7px 7px 16px var(--shadow-lo), -7px -7px 16px var(--shadow-hi);
        }
        div[data-testid="stTabs"] button[aria-selected="true"] {
            background: linear-gradient(135deg, rgba(79, 125, 243, 0.16), rgba(121, 196, 183, 0.18));
            color: var(--ink);
            box-shadow: inset 4px 4px 8px rgba(175, 187, 203, 0.55), inset -4px -4px 8px rgba(255,255,255,0.85);
        }
        div[data-testid="stMetric"] {
            background: var(--panel);
            border: 1px solid transparent;
            border-radius: 22px;
            padding: 0.9rem 1rem;
            box-shadow: 14px 14px 30px var(--shadow-lo), -14px -14px 30px var(--shadow-hi);
        }
        div[data-testid="stMetricLabel"], div[data-testid="stMetricValue"] {
            color: var(--ink);
        }
        .hero-shell {
            border: 1px solid rgba(255,255,255,0.55);
            border-radius: 30px;
            padding: 1.4rem 1.5rem;
            background:
                linear-gradient(145deg, #eef3f9 0%, #e2e9f2 100%);
            box-shadow: 24px 24px 46px rgba(168, 180, 197, 0.78), -18px -18px 38px rgba(255,255,255,0.96);
            margin-bottom: 1rem;
        }
        .hero-kicker {
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 0.16em;
            font-size: 0.78rem;
            margin-bottom: 0.55rem;
        }
        .hero-title {
            font-size: 2.1rem;
            line-height: 1.15;
            font-weight: 800;
            color: var(--ink);
            margin-bottom: 0.5rem;
        }
        .hero-copy {
            color: var(--muted);
            font-size: 1rem;
            max-width: 62rem;
        }
        .pill-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin-top: 1rem;
        }
        .pill {
            border: 1px solid rgba(255,255,255,0.6);
            background: var(--panel);
            border-radius: 999px;
            padding: 0.45rem 0.8rem;
            color: var(--ink);
            font-size: 0.9rem;
            box-shadow: 10px 10px 22px rgba(171, 183, 200, 0.72), -8px -8px 16px rgba(255,255,255,0.92);
        }
        .panel-note {
            border: 1px solid rgba(255,255,255,0.65);
            background: var(--panel);
            border-radius: 24px;
            padding: 1rem 1.1rem;
            box-shadow: 18px 18px 36px rgba(169, 181, 198, 0.74), -14px -14px 28px rgba(255,255,255,0.94);
        }
        .panel-note h4 {
            margin: 0 0 0.35rem;
            color: var(--ink);
        }
        .panel-note p {
            margin: 0;
            color: var(--muted);
        }
        div[data-testid="stTextInputRoot"] > div,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stSelectbox"] > div,
        div[data-testid="stMultiSelect"] > div {
            background: var(--panel) !important;
            border-radius: 18px !important;
            border: 1px solid rgba(255,255,255,0.6) !important;
            box-shadow: inset 5px 5px 10px rgba(188, 199, 214, 0.65), inset -5px -5px 10px rgba(255,255,255,0.92) !important;
        }
        div[data-baseweb="select"] > div,
        textarea, input {
            color: var(--ink) !important;
        }
        /* Phase 3.2: Buttons with smooth transitions */
        .stButton > button,
        .stDownloadButton > button {
            border-radius: 18px !important;
            border: 1px solid rgba(255,255,255,0.65) !important;
            background: linear-gradient(145deg, #eef3f9 0%, #dfe7f1 100%) !important;
            color: var(--ink) !important;
            box-shadow: 6px 6px 14px rgba(169, 181, 198, 0.65), -6px -6px 14px rgba(255,255,255,0.92) !important;
            transition: box-shadow 0.2s ease, transform 0.15s ease !important;
        }
        .stButton > button:hover,
        .stDownloadButton > button:hover {
            box-shadow: 10px 10px 22px rgba(169, 181, 198, 0.80), -8px -8px 18px rgba(255,255,255,0.96) !important;
            transform: translateY(-1px);
        }
        .stButton > button:active,
        .stDownloadButton > button:active {
            box-shadow: inset 3px 3px 8px rgba(169, 181, 198, 0.5), inset -3px -3px 8px rgba(255,255,255,0.8) !important;
            transform: translateY(0);
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, rgba(79, 125, 243, 0.22), rgba(121, 196, 183, 0.24)) !important;
        }
        .stButton > button[kind="primary"]:hover {
            background: linear-gradient(135deg, rgba(79, 125, 243, 0.35), rgba(121, 196, 183, 0.35)) !important;
        }
        /* Phase 3.2: Reduce shadow — remove box-shadow from container elements
           Keep shadow only on: metric cards, hero, pills (on hover), buttons (on hover) */
        div[data-testid="stDataFrame"] {
            border-radius: 24px !important;
            background: var(--panel) !important;
            border: 1px solid rgba(255,255,255,0.62) !important;
            overflow: hidden;
        }
        /* Alternating row colors for readability */
        div[data-testid="stDataFrame"] tbody tr:nth-child(even) td {
            background: rgba(79, 125, 243, 0.04) !important;
        }
        div[data-testid="stForm"],
        div[data-testid="stExpander"] {
            border-radius: 20px !important;
            background: var(--panel) !important;
            border: 1px solid rgba(255,255,255,0.62) !important;
        }
        div[data-testid="stAlert"] {
            border-radius: 18px !important;
            box-shadow: 8px 8px 18px rgba(169, 181, 198, 0.35), -8px -8px 18px rgba(255,255,255,0.8) !important;
        }
        .lift-card {
            border-radius: 22px;
            padding: 0.95rem 1rem;
            background: linear-gradient(145deg, #eef3f9 0%, #e3eaf3 100%);
            border: 1px solid rgba(255,255,255,0.7);
            box-shadow: 16px 16px 30px rgba(170, 182, 198, 0.72), -12px -12px 24px rgba(255,255,255,0.94);
        }
        .lift-card strong {
            color: var(--ink);
        }
        .lift-card span {
            color: var(--muted);
            display: block;
            margin-bottom: 0.25rem;
            font-size: 0.88rem;
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


def update_env_file(updates: dict) -> None:
    current = {}
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r", encoding="utf-8") as file:
            for raw_line in file.read().splitlines():
                if "=" not in raw_line or raw_line.strip().startswith("#"):
                    continue
                key, value = raw_line.split("=", 1)
                current[key.strip()] = value

    for key, value in updates.items():
        if value:
            current[key] = value.strip()

    with open(ENV_PATH, "w", encoding="utf-8") as file:
        for key, value in current.items():
            file.write(f"{key}={value}\n")


def save_api_keys(serper_key: str, openai_key: str) -> str:
    updates = {}
    if serper_key.strip():
        os.environ["SERPER_API_KEY"] = serper_key.strip()
        updates["SERPER_API_KEY"] = serper_key.strip()
    if openai_key.strip():
        os.environ["OPENAI_API_KEY"] = openai_key.strip()
        updates["OPENAI_API_KEY"] = openai_key.strip()
    if updates:
        update_env_file(updates)
        return "Đã lưu API keys vào môi trường chạy và file .env."
    return "Không có key mới để lưu."


def save_credentials_file(uploaded_file) -> str:
    creds_data = json.load(uploaded_file)
    with open(CREDS_PATH, "w", encoding="utf-8") as file:
        json.dump(creds_data, file, indent=2, ensure_ascii=False)
    return f"Đã lưu credentials vào {os.path.basename(CREDS_PATH)}."


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
        return pd.read_csv(DB_PATH, encoding="utf-8-sig")
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


def validate_run_request(keywords: list[str], enable_serp: bool) -> list[str]:
    problems = []
    if not keywords:
        problems.append("Cần nhập ít nhất 1 keyword.")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        problems.append("Thiếu `OPENAI_API_KEY`.")
    if enable_serp and not os.environ.get("SERPER_API_KEY", "").strip():
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
    # Phase 4.1: Include schema version for worker validation
    return {
        "schema_version": 1,
        "keywords": keywords,
        "creds_path": CREDS_PATH if os.path.exists(CREDS_PATH) else None,
        "sheet_url": sheet_url,
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

    error_file = open(ERROR_LOG_PATH, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", "worker.py"],
        cwd=BASE_DIR,
        stdout=error_file,
        stderr=error_file,
    )
    # Phase 1.2: Ghi PID thật sau khi xác nhận Popen thành công
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
            headers = pd.read_csv(DB_PATH, nrows=0, encoding="utf-8-sig")
            headers.to_csv(DB_PATH, index=False, encoding="utf-8-sig")
            messages.append("Đã reset database CSV cục bộ.")
        except Exception as exc:
            messages.append(f"Reset CSV lỗi: {exc}")

    glog = GSheetLogger(
        creds_path=CREDS_PATH if os.path.exists(CREDS_PATH) else None,
        sheet_url=sheet_url,
    )
    if glog.connect():
        try:
            glog.worksheet.batch_clear(["A2:R10000"])
            messages.append("Đã xóa dữ liệu cũ trên Google Sheet.")
        except Exception as exc:
            messages.append(f"Không xóa được Google Sheet: {exc}")
    else:
        messages.append("Không kết nối được Google Sheet để reset.")

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
    if not IS_CLOUD or not st.session_state.get("batch_running"):
        return

    keywords = st.session_state.batch_keywords
    batch_idx = st.session_state.batch_idx
    if batch_idx >= len(keywords):
        st.session_state.batch_running = False
        st.session_state.batch_current_keyword = ""
        st.session_state.batch_last_event = (
            f"Hoàn tất {len(st.session_state.batch_results)} keyword trên Streamlit Cloud."
        )
        return

    keyword = keywords[batch_idx]
    st.session_state.batch_current_keyword = keyword

    try:
        project = None
        project_id = st.session_state.batch_project_id
        if project_id:
            pm = ProjectManager()
            project = pm.get_by_id(project_id)

        from main_generator import _process_single_topic

        glog = None
        if os.path.exists(CREDS_PATH):
            glog = GSheetLogger(
                creds_path=CREDS_PATH,
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
        st.session_state.batch_results.append(
            {"keyword": keyword, "status": "done", "file": result or "N/A"}
        )
        st.session_state.batch_last_event = f"Đã xử lý xong: {keyword}"
    except Exception as exc:
        st.session_state.batch_results.append(
            {"keyword": keyword, "status": f"error: {exc}", "file": ""}
        )
        st.session_state.batch_last_event = f"Lỗi khi xử lý `{keyword}`: {exc}"

    st.session_state.batch_idx = batch_idx + 1
    if st.session_state.batch_idx < len(keywords):
        st.rerun()
    else:
        st.session_state.batch_running = False
        st.session_state.batch_current_keyword = ""


def render_hero(active_project, worker_running: bool, metrics: dict) -> None:
    mode_label = "Cloud" if IS_CLOUD else "Local"
    project_label = active_project.brand_name if active_project else "Chưa chọn project"
    worker_label = "Đang chạy" if worker_running or st.session_state.batch_running else "Sẵn sàng"
    st.markdown(
        f"""
        <div class="hero-shell">
            <div class="hero-kicker">Semantic SEO Workflow</div>
            <div class="hero-title">Content Brief Generator</div>
            <div class="hero-copy">
                Tạo content brief từ keyword, theo dõi pipeline theo thời gian thực và quản lý source context
                cho từng project mà không phải lần mò qua nhiều khu vực UI rời rạc.
            </div>
            <div class="pill-row">
                <div class="pill">Chế độ: <strong>{mode_label}</strong></div>
                <div class="pill">Project: <strong>{project_label}</strong></div>
                <div class="pill">Tiến trình: <strong>{worker_label}</strong></div>
                <div class="pill">Bản ghi: <strong>{metrics["total"]}</strong></div>
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
    st.markdown(
        """
        <div class="panel-note">
            <h4>Luồng thao tác đề xuất</h4>
            <p>1. Chọn project và cấu hình. 2. Nạp danh sách keyword. 3. Bật các module cần dùng. 4. Chạy batch và theo dõi log ở cột phải.</p>
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
            st.subheader("1. Danh sách keyword")
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
                    placeholder="thép tấm là gì\nthi công thạch cao giá bao nhiêu\nprotein cho người ăn chay",
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
            st.subheader("2. Thiết lập pipeline")
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
            st.subheader("3. Kết nối & chạy job")
            sheet_url = st.text_input(
                "Google Sheet URL",
                value=DEFAULT_SHEET_URL,
                help="Có thể để mặc định nếu đang dùng sheet cũ.",
            )

            openai_ready = "Có" if os.environ.get("OPENAI_API_KEY") else "Thiếu"
            serper_ready = "Có" if os.environ.get("SERPER_API_KEY") else "Thiếu"
            project_ready = active_project.brand_name if active_project else "Chưa chọn"

            stat1, stat2 = st.columns(2)
            stat1.metric("OpenAI", openai_ready)
            stat2.metric("Serper", serper_ready)
            st.markdown(
                f"""
                <div class="lift-card">
                    <span>Project đang áp dụng</span>
                    <strong>{project_ready}</strong>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.caption("Khi chạy lại cùng một keyword, app sẽ cập nhật lại chính dòng cũ trên Google Sheet để bạn dễ theo dõi.")

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

            if refresh:
                st.rerun()

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
                    st.success("Đã khởi chạy worker nền.")
                    time.sleep(0.8)
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
            # Phase 1.5 fix: chỉ hiện progress bar khi đang chạy batch, không khi idle (0%)
            # Phase 3.3: Step indicator với mô tả tiến trình
            if st.session_state.batch_running or worker_running:
                progress = (current_idx / total_batch) if total_batch else 0.0
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
            st.subheader("4. Log runtime")
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

    return sheet_url


def render_results_tab(df_db: pd.DataFrame) -> None:
    st.subheader("Kết quả & theo dõi")

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
            placeholder="VD: thép tấm, giá thép,...",
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
            "Báo cáo phân tích dữ liệu",
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

    detail_tabs = st.tabs(["Brief", "Phân tích", "Koray", "Tóm tắt"])

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
        analysis = str(selected_row.get("Báo cáo phân tích dữ liệu", "") or "")
        if analysis and analysis != "nan":
            st.markdown(analysis)
        else:
            st.info("Chưa có báo cáo phân tích.")

    with detail_tabs[2]:
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

    with detail_tabs[3]:
        quick = {
            "Keyword": selected_row.get("Keyword", ""),
            "Trạng thái": selected_row.get("Trạng thái", ""),
            "Intent": selected_row.get("Search Intent", ""),
            "Top đối thủ": selected_row.get("Top 3 Đối thủ", ""),
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
            placeholder="VD: ASTM A36, JIS G3101, TCVN 1651",
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
    left, right = st.columns([1, 1], gap="large")

    with left:
        with st.container(border=True):
            st.markdown("#### API keys")
            st.caption("Lưu vào `.env` để worker local và app dùng lại được ở lần chạy sau.")
            with st.form("api_form"):
                serper_key = st.text_input(
                    "Serper API Key",
                    value=os.environ.get("SERPER_API_KEY", ""),
                    type="password",
                )
                openai_key = st.text_input(
                    "OpenAI API Key",
                    value=os.environ.get("OPENAI_API_KEY", ""),
                    type="password",
                )
                submitted = st.form_submit_button("Lưu API keys", type="primary", use_container_width=True)

            if submitted:
                st.success(save_api_keys(serper_key, openai_key))

    with right:
        with st.container(border=True):
            st.markdown("#### Google Sheets")
            st.caption("Dùng để đồng bộ tiến trình pipeline theo thời gian thực.")
            st.text_input("Credentials path", value=CREDS_PATH, disabled=True)
            uploaded_creds = st.file_uploader(
                "Upload service account JSON",
                type=["json"],
                key="settings_creds",
            )
            if uploaded_creds is not None:
                try:
                    st.success(save_credentials_file(uploaded_creds))
                except Exception as exc:
                    st.error(f"Lưu credentials lỗi: {exc}")

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
    ["Tạo brief", "Kết quả", "Projects", "Cài đặt"]
)

with tab_generate:
    current_sheet_url = render_generate_tab(active_project, worker_running)

with tab_results:
    render_results_tab(df_db)

with tab_projects:
    render_projects_tab(pm, active_project)

with tab_settings:
    render_settings_tab(current_sheet_url)
