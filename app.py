import streamlit as st
import pandas as pd
import os
import sys
import time
import json

# ── Load .env TRƯỚC KHI import config (đảm bảo API keys sẵn sàng ngay lần chạy đầu) ──
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
except ImportError:
    pass

# ── Phase 37: Streamlit Cloud compatibility ──
# Detect cloud environment: Streamlit Cloud sets SHARE_URL env var
IS_CLOUD = bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("STREAMLIT_CLOUD"))
IS_LOCAL = not IS_CLOUD

from modules.gsheet_logger import GSheetLogger

st.set_page_config(page_title="Content Brief Generator", page_icon="📝", layout="wide")

# Xử lý CSS
st.markdown("""
<style>
    /* Chỉnh màu cho toàn bộ Text Area và Text Input (cả ngoài form) */
    .stTextArea>div>div>textarea,
    .stTextInput>div>div>input {
        background-color: #F8F9FA !important;
        color: #1A1A2E !important;
        border: 1px solid #555 !important;
        border-radius: 6px !important;
    }
    .stTextArea>div>div>textarea:focus,
    .stTextInput>div>div>input:focus {
        border-color: #4DA8DA !important;
        box-shadow: 0 0 0 2px rgba(77, 168, 218, 0.3) !important;
    }
    .stTextArea>div>div>textarea::placeholder,
    .stTextInput>div>div>input::placeholder {
        color: #666666 !important;
    }
    
    .status-running { color: #f39c12; font-weight: bold; }
    .status-done { color: #2ecc71; font-weight: bold; }
    .status-error { color: #e74c3c; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

st.title("🚀 AI Content Brief Generator")
st.markdown("Hệ thống tự động xây dựng Content Brief chuẩn SEO dựa trên SERP, Entity và Topical Map.")

# --- SIDEBAR: Cấu hình ---
with st.sidebar:
    st.header("⚙️ Cấu hình hệ thống")

    # ── Phase 33: PROJECT MANAGEMENT (Compact sidebar controls) ──
    st.subheader("🏢 Active Project (Source Context)")
    active_project = None  # Gap 5 fix: init trước try block
    try:
        from modules.project_manager import ProjectManager
        pm = ProjectManager()
        active_project = pm.get_active()
        all_projects = pm.get_all()

        if active_project:
            st.success(f"✅ Active: **{active_project.brand_name}**")
            st.caption(f"🌐 {active_project.domain}")
        else:
            st.info("⚠️ Chưa chọn Project nào")

        if all_projects:
            project_options = {p.id: f"[{p.id}] {p.name}" for p in all_projects}
            selected_pid = st.selectbox(
                "Project:",
                options=list(project_options.keys()),
                format_func=lambda x: project_options[x],
                index=0,
                label_visibility="collapsed",
            )
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                if st.button("✅ Set Active", use_container_width=True):
                    pm.set_active(selected_pid)
                    st.rerun()
            with c2:
                if st.button("✏️", use_container_width=True, key="btn_edit_project",
                             help="Sửa Project"):
                    st.session_state["edit_project_id"] = selected_pid
                    st.session_state["show_project_form"] = True
            with c3:
                if st.button("🗑️", use_container_width=True, key="btn_del_project",
                             help="Xóa Project"):
                    st.session_state["confirm_delete_pid"] = selected_pid

        # Confirm delete popup
        if st.session_state.get("confirm_delete_pid"):
            pid_to_del = st.session_state["confirm_delete_pid"]
            proj_to_del = pm.get_by_id(pid_to_del)
            name_to_del = proj_to_del.name if proj_to_del else f"ID={pid_to_del}"
            st.warning(f"⚠️ Xóa **{name_to_del}**?")
            cd1, cd2 = st.columns(2)
            with cd1:
                if st.button("❌ Hủy", use_container_width=True, key="btn_del_cancel"):
                    st.session_state.pop("confirm_delete_pid", None)
                    st.rerun()
            with cd2:
                if st.button("✅ Xác nhận Xóa", use_container_width=True,
                             type="primary", key="btn_del_confirm"):
                    pm.delete(pid_to_del)
                    st.session_state.pop("confirm_delete_pid", None)
                    if active_project and active_project.id == pid_to_del:
                        active_project = None
                    st.rerun()

        if st.button("➕ Tạo Project mới", use_container_width=True):
            st.session_state.pop("edit_project_id", None)
            st.session_state["show_project_form"] = True

    except Exception as pm_err:
        st.warning(f"⚠️ Project Manager: {pm_err}")
        active_project = None

    st.markdown("---")
    st.subheader("🔑 API Keys")
    st.caption("Lưu trực tiếp vào backend để Worker có thể sử dụng")
    
    # Lấy key hiện hành từ env
    curr_serper = os.environ.get("SERPER_API_KEY", "")
    curr_openai = os.environ.get("OPENAI_API_KEY", "")
    
    with st.form("api_key_form"):
        serper_key = st.text_input("Serper API Key", value=curr_serper, type="password")
        openai_key = st.text_input("OpenAI API Key", value=curr_openai, type="password")
        
        save_keys_btn = st.form_submit_button("Lưu API Keys vào Backend", type="primary", use_container_width=True)
        
        if save_keys_btn:
            # Ghi vào environment
            if serper_key:
                os.environ["SERPER_API_KEY"] = serper_key.strip()
            if openai_key:
                os.environ["OPENAI_API_KEY"] = openai_key.strip()
                
            # Cập nhật file .env
            env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
            env_content = ""
            if os.path.exists(env_path):
                with open(env_path, "r", encoding="utf-8") as f:
                    env_content = f.read()
            
            lines = env_content.splitlines()
            new_lines = []
            serper_found = False
            openai_found = False
            
            for line in lines:
                if line.startswith("SERPER_API_KEY="):
                    new_lines.append(f"SERPER_API_KEY={serper_key.strip()}")
                    serper_found = True
                elif line.startswith("OPENAI_API_KEY="):
                    new_lines.append(f"OPENAI_API_KEY={openai_key.strip()}")
                    openai_found = True
                else:
                    new_lines.append(line)
                    
            if not serper_found:
                new_lines.append(f"SERPER_API_KEY={serper_key.strip()}")
            if not openai_found:
                new_lines.append(f"OPENAI_API_KEY={openai_key.strip()}")
                
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("\n".join(new_lines) + "\n")
                
            st.success("✅ Đã lưu API Keys mới vào .env!")
            time.sleep(1)
            st.rerun()
            
    if not curr_serper or not curr_openai:
        st.warning("⚠️ Cần điền cả Serper và OpenAI API Key để Worker có thể chạy.")
    
    st.subheader("Google Sheets Integration")
    sheet_url = st.text_input("Google Sheet URL", value="https://docs.google.com/spreadsheets/d/1i_lgFmoB1LJq2Lt01CwDlOk3hVbQxPiZ4LqGqf8mgwM")
    
    creds_file = st.file_uploader("Upload Service Account JSON", type=["json"])
    creds_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gen-lang-client-0396271616-70425b3ad4fb.json")
    
    if creds_file is not None:
        try:
            creds_data = json.load(creds_file)
            with open(creds_path, "w", encoding="utf-8") as f:
                json.dump(creds_data, f, indent=2)
            st.success("✅ Đã lưu credentials")
        except Exception as e:
            st.error(f"Lỗi: {str(e)}")
            
    st.markdown("---")
    st.subheader("Pipeline Modules")
    enable_serp = st.checkbox("Crawl SERP + Competitors", value=True)
    enable_network = st.checkbox("Semantic Keyword Network", value=True)
    enable_context = st.checkbox("Context Builder (Chưa dùng AI API)", value=False)
    enable_linking = st.checkbox("Internal Linking (Topical Map / Auto H2)", value=True)
    
    st.markdown("---")
    st.subheader("✍️ Phong cách viết (Methodology)")
    from modules.article_writer import METHODOLOGY_LABELS
    methodology_options = list(METHODOLOGY_LABELS.keys())
    methodology_labels = list(METHODOLOGY_LABELS.values())
    selected_methodology = st.selectbox(
        "Chọn Methodology",
        options=methodology_options,
        format_func=lambda x: METHODOLOGY_LABELS.get(x, x),
        index=0,  # Default: Auto-Detect
        help="Quyết định phong cách viết bài: Evidence-Based (có dẫn chứng), Product Review (có Pros/Cons), Step-by-Step (hướng dẫn từng bước)."
    )
    
    st.markdown("---")
    st.subheader("🔧 Quản trị Dữ liệu")
    if st.button("🗑️ RESET DATABASE", type="primary", use_container_width=True):
        # 1. Reset Local CSV Database
        db_path = "database_v2.csv"
        if os.path.exists(db_path):
            try:
                # Đọc header và ghi đè file rỗng
                df_headers = pd.read_csv(db_path, nrows=0, encoding="utf-8-sig")
                df_headers.to_csv(db_path, index=False, encoding="utf-8-sig")
            except Exception:
                pass
                
        # 2. Reset Google Sheet (Dòng 2 trở đi)
        glog = GSheetLogger(creds_path=creds_path if os.path.exists(creds_path) else None, sheet_url=sheet_url)
        if glog.connect():
            try:
                glog.worksheet.batch_clear(["A2:R10000"])
                st.success("✅ Đã xóa sạch dữ liệu cũ trên Google Sheet!")
            except Exception as e:
                st.error(f"❌ Lỗi khi xóa Google Sheet: {str(e)}")
        else:
            st.warning("⚠️ Không thể kết nối Google Sheet để xóa dữ liệu. Hãy kiểm tra Credentials!")
            
        time.sleep(1.5)
        st.rerun()

# --- PROJECT FORM (Main Content — Gap 2 fix: form ở main area, 4 tabs) ---
if st.session_state.get("show_project_form"):
    try:
        from modules.project_manager import ProjectManager as _PM
        _pm = _PM()
        _edit_id = st.session_state.get("edit_project_id")
        _edit_proj = _pm.get_by_id(_edit_id) if _edit_id else None
        _form_title = f"✏️ Sửa Project: **{_edit_proj.name}**" if _edit_proj else "➕ **Tạo Project mới**"

        st.markdown("---")
        st.markdown(f"### 🏢 {_form_title}")

        # ── Custom CSS: tăng contrast cho form trong dark mode ──
        st.markdown("""
        <style>
        /* Form container — viền accent + padding */
        [data-testid="stForm"] {
            border: 2px solid #4DA8DA !important;
            border-radius: 12px;
            padding: 1.5rem 1rem;
            background: rgba(30, 40, 55, 0.6);
        }
        /* Section headers (####) nổi bật trong form */
        [data-testid="stForm"] h4 {
            color: #FFFFFF !important;
            font-size: 1.15rem !important;
            font-weight: 700 !important;
            border-bottom: 2px solid #4DA8DA;
            padding-bottom: 6px;
            margin-top: 1.2rem;
            margin-bottom: 0.8rem;
        }
        /* Labels sáng hơn */
        [data-testid="stForm"] label {
            color: #D0D8E8 !important;
            font-weight: 500 !important;
        }
        /* Input fields — nền sáng, text đen dễ đọc */
        [data-testid="stForm"] input,
        [data-testid="stForm"] textarea {
            background: #F8F9FA !important;
            color: #1A1A2E !important;
            border: 1px solid #555 !important;
            border-radius: 6px !important;
        }
        [data-testid="stForm"] input:focus,
        [data-testid="stForm"] textarea:focus {
            border-color: #4DA8DA !important;
            box-shadow: 0 0 0 2px rgba(77, 168, 218, 0.3) !important;
        }
        /* Placeholder text */
        [data-testid="stForm"] input::placeholder,
        [data-testid="stForm"] textarea::placeholder {
            color: #999 !important;
        }
        </style>
        """, unsafe_allow_html=True)

        with st.form("project_form_main"):
            # ── 🏷️ BRAND INFO ──
            st.markdown("#### 🏷️ Brand Info")
            cc1, cc2 = st.columns(2)
            with cc1:
                f_name     = st.text_input("Tên Project *", value=_edit_proj.name if _edit_proj else "")
                f_brand    = st.text_input("Brand Name *", value=_edit_proj.brand_name if _edit_proj else "")
            with cc2:
                f_domain   = st.text_input("Domain *", value=_edit_proj.domain if _edit_proj else "",
                                           placeholder="theptranlong.vn")
                f_company  = st.text_input("Tên công ty đầy đủ", value=_edit_proj.company_full_name if _edit_proj else "")
            cc3, cc4 = st.columns(2)
            with cc3:
                f_industry = st.text_input("Ngành / Lĩnh vực", value=_edit_proj.industry if _edit_proj else "")
            with cc4:
                f_customers = st.text_input("Khách hàng mục tiêu", value=_edit_proj.target_customers if _edit_proj else "")

            # ── 📦 SẢN PHẨM & USP ──
            st.markdown("#### 📦 Sản phẩm & USP")
            f_products = st.text_area("Sản phẩm chính (mỗi dòng 1 sản phẩm)", height=100,
                                      value=_edit_proj.main_products if _edit_proj else "")
            f_usp      = st.text_area("USP / Lợi thế cạnh tranh", height=80,
                                      value=_edit_proj.usp if _edit_proj else "")
            f_competitors = st.text_input(
                "Brand đối thủ (cách nhau bằng dấu phẩy — sẽ KHÔNG đặt làm H2 Main)",
                value=_edit_proj.competitor_brands if _edit_proj else ""
            )

            # ── ⚙️ KỸ THUẬT & TONE ──
            st.markdown("#### ⚙️ Kỹ thuật & Tone")
            ct1, ct2, ct3 = st.columns(3)
            with ct1:
                f_tone     = st.text_input("Tone & giọng văn", value=_edit_proj.tone if _edit_proj else "",
                                           placeholder="Chuyên nghiệp, thực tế")
            with ct2:
                f_standards = st.text_input("Tiêu chuẩn kỹ thuật", value=_edit_proj.technical_standards if _edit_proj else "",
                                            placeholder="ASTM A36, JIS G3101")
            with ct3:
                f_geo      = st.text_input("GEO Keywords", value=_edit_proj.geo_keywords if _edit_proj else "",
                                           placeholder="Hà Nội, Miền Bắc")

            # ── 📞 NAP ──
            st.markdown("#### 📞 NAP (Name / Address / Phone)")
            cn1, cn2 = st.columns(2)
            with cn1:
                f_hotline  = st.text_input("Hotline / Zalo", value=_edit_proj.hotline if _edit_proj else "",
                                           placeholder="0912 345 678")
                f_email    = st.text_input("Email", value=_edit_proj.email if _edit_proj else "")
            with cn2:
                f_address  = st.text_input("Địa chỉ trụ sở", value=_edit_proj.address if _edit_proj else "")
                f_warehouse = st.text_input("Kho / Chi nhánh", value=_edit_proj.warehouse if _edit_proj else "",
                                            placeholder="Kho Đông Anh, Chi nhánh Nam Từ Liêm")

            sb1, sb2 = st.columns([3, 1])
            with sb1:
                _submitted = st.form_submit_button("💾 Lưu Project", use_container_width=True, type="primary")
            with sb2:
                _cancelled = st.form_submit_button("❌ Hủy", use_container_width=True)

            if _cancelled:
                st.session_state.pop("show_project_form", None)
                st.session_state.pop("edit_project_id", None)
                st.rerun()

            if _submitted:
                if not f_name or not f_brand or not f_domain:
                    st.error("❌ Cần điền: Tên Project (*), Brand Name (*), Domain (*)")
                else:
                    _pdata = {
                        "name": f_name, "brand_name": f_brand, "domain": f_domain,
                        "company_full_name": f_company, "industry": f_industry,
                        "main_products": f_products, "usp": f_usp,
                        "target_customers": f_customers, "competitor_brands": f_competitors,
                        "tone": f_tone, "technical_standards": f_standards,
                        "geo_keywords": f_geo, "hotline": f_hotline,
                        "email": f_email, "address": f_address, "warehouse": f_warehouse,
                    }
                    if _edit_id:
                        _pm.update(_edit_id, _pdata)
                        st.success(f"✅ Đã cập nhật Project '{f_name}'!")
                    else:
                        _pm.create(_pdata)
                        st.success(f"✅ Đã tạo Project mới '{f_name}'!")
                    st.session_state.pop("show_project_form", None)
                    st.session_state.pop("edit_project_id", None)
                    st.rerun()

        st.markdown("---")
    except Exception as _pf_err:
        st.error(f"❌ Project Form lỗi: {_pf_err}")

# --- MAIN CONTENT ---
col1, col2 = st.columns([1, 1])


with col1:
    st.subheader("📥 Dữ liệu đầu vào")
    
    input_method = st.radio("Chọn cách nhập Keyword:", ["Nhập thủ công (Text)", "Upload file CSV"])
    
    keywords = []
    if input_method == "Nhập thủ công (Text)":
        kw_text = st.text_area("Nhập danh sách Keyword (mỗi dòng 1 từ khóa):", height=150, placeholder="Máy lọc nước RO\nBáo giá thi công thạch cao\nProtein cho người ăn chay")
        if kw_text:
            keywords = [k.strip() for k in kw_text.split("\n") if k.strip()]
    else:
        uploaded_csv = st.file_uploader("Tải file CSV (Cột 'Keyword')", type=["csv"])
        if uploaded_csv:
            df = pd.read_csv(uploaded_csv)
            if 'Keyword' in df.columns:
                keywords = df['Keyword'].dropna().tolist()
            else:
                st.error("File CSV phải có cột tên là 'Keyword'")
                
    st.info(f"Tổng số từ khóa cần xử lý: **{len(keywords)}**")

with col2:
    st.subheader("📈 Real-time Log")
    log_container = st.empty()
    progress_bar = st.progress(0)
    
st.markdown("---")
st.subheader("📊 Data Preview")
result_table = st.empty()
results_df = pd.DataFrame(columns=["Keyword", "Status", "Intent", "Headings", "Brief File"])
result_table.dataframe(results_df, use_container_width=True)

# --- XỬ LÝ KHI BẤM NÚT & MONITOR ---
col_action, col_status = st.columns([1, 2])

# Kiểm tra trạng thái worker
worker_running = os.path.exists("worker_lock.txt")

with col_action:
    if not worker_running:
        if st.button("🚀 START BATCH PROCESS", type="primary", use_container_width=True):
            if not keywords:
                st.warning("Vui lòng nhập ít nhất 1 từ khóa!")
                st.stop()
                
            # Tạo job payload
            job_data = {
                "keywords": keywords,
                "creds_path": creds_path if os.path.exists(creds_path) else None,
                "sheet_url": sheet_url,
                "config": {
                    "enable_serp": enable_serp,
                    "enable_network": enable_network,
                    "enable_context": enable_context,
                    "enable_linking": enable_linking,
                    "methodology": selected_methodology,
                    "project_id": active_project.id if active_project else None,  # Phase 33
                }
            }
            
            with open("job_queue.json", "w", encoding="utf-8") as f:
                json.dump(job_data, f, ensure_ascii=False, indent=2)

            if IS_CLOUD:
                # Streamlit Cloud: chạy inline trong Streamlit (không dùng subprocess/worker)
                st.warning("☁️ Streamlit Cloud: Chạy pipeline trực tiếp (từng keyword). Với batch lớn, dùng local thay thế.")
                # Phase 37: Inline pipeline for cloud — khởi tạo session state
                if "batch_results" not in st.session_state:
                    st.session_state.batch_results = []
                if "batch_running" not in st.session_state:
                    st.session_state.batch_running = False
                if "batch_keywords" not in st.session_state:
                    st.session_state.batch_keywords = keywords
                if "batch_idx" not in st.session_state:
                    st.session_state.batch_idx = 0
                st.session_state.batch_running = True
                st.session_state.batch_keywords = keywords
                st.session_state.batch_idx = 0
                st.session_state.batch_results = []
                st.session_state.batch_config = job_data["config"]
                st.session_state.batch_project_id = job_data["config"].get("project_id")
                st.session_state.batch_sheet_url = sheet_url
                st.success("✅ Đã khởi tạo batch! Keyword sẽ chạy khi bạn reload trang.")
                st.info("💡 Mẹo: Với batch >5 keywords, dùng **local** thay vì cloud.")
                st.rerun()
            else:
                # Local: dùng worker ngầm bình thường
                import subprocess
                error_file = open("worker_error.log", "w", encoding="utf-8")
                subprocess.Popen(
                    [sys.executable, "-u", "worker.py"],  # -u = unbuffered
                    stderr=error_file,
                    stdout=error_file,
                )

                with open("worker_lock.txt", "w", encoding="utf-8") as f:
                    f.write("STARTING")

                st.success("✅ Đã khởi chạy tiến trình ngầm! Đang tải dữ liệu...")
                time.sleep(1)
                st.rerun()
    else:
        if IS_CLOUD:
            st.info("☁️ Cloud mode: Batch đã khởi tạo. Reload trang để chạy tiếp.")
        else:
            st.button("🔄 Tiến trình đang chạy ngầm...", type="secondary", disabled=True, use_container_width=True)
        if st.button("🛑 Dừng Worker (Force Kill)", type="primary"):
            # Đọc PID từ lock file và kill (chỉ mượn os.remove tạm thời cho mock)
            try:
                with open("worker_lock.txt", "r") as f:
                    pid = int(f.read().strip())
                if os.name == 'nt':
                    os.system(f"taskkill /F /PID {pid}")
                else:
                    os.system(f"kill -9 {pid}")
            except Exception:
                pass
            if os.path.exists("worker_lock.txt"):
                os.remove("worker_lock.txt")
            st.rerun()

st.markdown("---")
st.subheader("📊 Data Monitor (Auto-refresh: 3s)")

# ── Phase 37: Inline Batch Processor for Streamlit Cloud ──
if IS_CLOUD and st.session_state.get("batch_running"):
    batch_keywords = st.session_state.batch_keywords
    batch_idx = st.session_state.batch_idx
    batch_results = st.session_state.batch_results
    batch_project_id = st.session_state.batch_project_id
    batch_config = st.session_state.batch_config

    if batch_idx < len(batch_keywords):
        kw = batch_keywords[batch_idx]
        progress_bar.progress((batch_idx + 1) / len(batch_keywords))
        log_container.info(f"☁️ [{batch_idx+1}/{len(batch_keywords)}] Cloud: {kw}")

        try:
            from modules.project_manager import ProjectManager
            pm = ProjectManager()
            project = pm.get_by_id(batch_project_id) if batch_project_id else None
        except Exception:
            project = None

        try:
            from main_generator import generate_content_brief
            result = generate_content_brief(
                topic=kw,
                enable_serp=batch_config.get("enable_serp", True),
                enable_network=batch_config.get("enable_network", False),
                enable_context=batch_config.get("enable_context", False),
                enable_linking=batch_config.get("enable_linking", True),
                project=project,
            )
            batch_results.append({"keyword": kw, "status": "done", "file": result or "N/A"})
            log_container.success(f"  ✅ Done: {kw}")
        except Exception as cloud_err:
            batch_results.append({"keyword": kw, "status": f"error: {cloud_err}", "file": ""})
            log_container.error(f"  ❌ Error: {kw} — {cloud_err}")

        st.session_state.batch_idx = batch_idx + 1
        st.session_state.batch_results = batch_results
        st.rerun()
    else:
        # Batch complete
        st.session_state.batch_running = False
        results_df = pd.DataFrame(batch_results)
        result_table.dataframe(results_df, use_container_width=True)
        st.success(f"✅ Batch hoàn tất! {len(batch_results)} keywords đã xử lý.")
        progress_bar.progress(1.0)

# Load database hiển thị
df_db = pd.DataFrame()
db_path = "database_v2.csv"
if os.path.exists(db_path):
    try:
        df_db = pd.read_csv(db_path, encoding="utf-8-sig")
    except Exception:
        pass

if not df_db.empty:
    # Ẩn cột quá dài khỏi bảng tổng quan
    hide_cols = ["Full Content Brief", "Báo cáo phân tích dữ liệu",
                 "Macro Context", "EAV Table", "Attribute Filtration",
                 "FS/PAA Map", "Main/Supp Split", "Source Context Alignment", "Koray Quality Score"]
    display_df = df_db.drop(columns=hide_cols, errors="ignore")
    st.dataframe(display_df, use_container_width=True, height=400)

    # Tabs xem chi tiết
    tab_brief, tab_analysis, tab_koray = st.tabs([
        "📝 Content Briefs",
        "📊 Phân tích Dữ liệu",
        "🧠 Koray SEO Columns (L-R)",
    ])

    done_rows = df_db[df_db["Trạng thái"].str.contains("Done", na=False)]
    with tab_brief:
        if not done_rows.empty:
            last_done = done_rows.iloc[-1]
            with st.expander(f"📝 Xem trước Brief: {last_done['Keyword']}"):
                if "Full Content Brief" in df_db.columns:
                    st.markdown(str(last_done["Full Content Brief"]))
        else:
            st.info("Chưa có brief nào hoàn thành.")

    with tab_analysis:
        if not done_rows.empty:
            last_done = done_rows.iloc[-1]
            with st.expander(f"📊 Xem trước Phân tích: {last_done['Keyword']}"):
                if "Báo cáo phân tích dữ liệu" in df_db.columns:
                    st.markdown(str(last_done["Báo cáo phân tích dữ liệu"]))
        else:
            st.info("Chưa có dữ liệu phân tích.")

    with tab_koray:
        if not done_rows.empty:
            last_done = done_rows.iloc[-1]
            kw_name = last_done["Keyword"]
            st.markdown(f"### 🧠 Koray SEO Analysis: **{kw_name}**")

            koray_cols = [
                ("L", "Macro Context", "🌐"),
                ("M", "EAV Table", "📊"),
                ("N", "Attribute Filtration", "🔢"),
                ("O", "FS/PAA Map", "❓"),
                ("P", "Main/Supp Split", "📦"),
                ("Q", "Source Context Alignment", "🎯"),
                ("R", "Koray Quality Score", "📊"),
            ]
            for col_letter, col_name, icon in koray_cols:
                if col_name in df_db.columns:
                    val = str(last_done.get(col_name, ""))
                    if val and val not in ["nan", ""]:
                        with st.expander(f"{icon} Cột {col_letter}: {col_name}"):
                            st.markdown(val)
                    else:
                        st.caption(f"{icon} Cột {col_letter}: {col_name} — _(Chưa có dữ liệu)_")
        else:
            st.info("⚠️ Chưa có dữ liệu Koray. Hãy chạy pipeline trước!")
else:
    st.info("Chưa có dữ liệu nào trong Database.")

# Hiển thị Real-time Log
error_log_path = "worker_error.log"
if os.path.exists(error_log_path):
    try:
        with open(error_log_path, "r", encoding="utf-8", errors="replace") as ef:
            error_content = ef.read()
            lines = error_content.splitlines(True)
            if lines:
                last_lines = lines[-20:] if len(lines) > 20 else lines
                log_container.code("".join(last_lines), language="text")
                
        # Kiểm tra Crash nếu tiến trình không còn chạy
        if not worker_running and error_content.strip():
            # Nếu không có chữ HOÀN TẤT và có chữ LỖI/CRASH -> Là crash
            if "WORKER HOÀN TẤT" not in error_content and ("WORKER CRASH" in error_content or "Traceback" in error_content):
                st.error("💀 **WORKER ĐÃ CRASH!** Chi tiết lỗi:")
                st.code(error_content[-3000:], language="python")
                st.warning("Worker đã tắt đột ngột. Hãy sửa lỗi trên rồi bấm Start lại.")
    except Exception:
        pass

# Auto-refresh loop
if worker_running:
    st.caption("🔄 Đang tự động cập nhật bảng... (3s/lần)")
    time.sleep(3)
    st.rerun()
