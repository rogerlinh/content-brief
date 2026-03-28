# Deploy len Streamlit Cloud

Huong dan deploy Content Brief Generator len Streamlit Cloud.

---

## Buc 1: Cai dat Secrets tren Streamlit Cloud

1. Vao https://share.streamlit.io
2. Dang nhap GitHub
3. Chon repo: `rogerlinh/content-brief`
4. Chon branch: `main`
5. File chinh: `app.py`
6. **App URL:** Tu dat hoac de mac dinh

### Thiet lap Secrets

Tai trang cai dat app tren Streamlit Cloud, them cac bien:

```
OPENAI_API_KEY = sk-proj-...       # OpenAI API key
SERPER_API_KEY = ...                # Serper.dev API key
```

Luu y: Secrets duoc luu trong `.streamlit/secrets.toml` tren Streamlit Cloud, khong can day len GitHub.

---

## Buc 2: Kiem tra files can thiet

Da co san trong repo:

```
requirements.txt          # Dependencies
app.py                    # Main Streamlit app
.streamlit/
  config.toml             # Streamlit config (dark theme)
  secrets.toml            # Template (khong push secrets that)
.github/
  workflows/
    streamlit-deploy.yml  # Auto-test tren push
modules/                   # Tat ca modules
main_generator.py          # Pipeline chinh
worker.py                  # Background worker (chi local)
config.py                  # Cau hinh
```

---

## Buc 3: GitHub Actions (Tu dong)

Moi lan push len `main`, GitHub Actions tu dong:
1. Checkout code
2. Setup Python 3.11
3. Install dependencies
4. Verify syntax
5. Run `run_test.py`

Neu tests fail → deploy bi huy.

---

## Han che cua Streamlit Cloud

| Tinh nang | Cloud | Local |
|-----------|-------|-------|
| Giao dien Streamlit | ✅ | ✅ |
| Single keyword pipeline | ✅ | ✅ |
| Batch processing (inline) | ✅ | ✅ |
| Background worker | ❌ | ✅ |
| Ghi file (job_queue.json) | ❌ (session_state) | ✅ |
| SQLite database | ❌ (in-memory) | ✅ |
| SERP crawl (Playwright) | ⚠️ Co the loi | ✅ |

### Su dung dungluc

- **Local (may ban):** Bat ky tinh nang nao, worker ngam, SQLite, SERP crawl
- **Streamlit Cloud:** Giao dien + single/batch keywords (inline), API keys tu secrets

---

## Buc 4: Push code moi

```bash
cd /e/content-brief/content-brief

git add requirements.txt
git add .streamlit/config.toml
git add .github/workflows/streamlit-deploy.yml
git add app.py
git add .gitignore
git add DEPLOY_STREAMLIT.md

git status

git commit -m "feat: Streamlit Cloud deployment setup

- Add requirements.txt for cloud
- Add .streamlit/config.toml (dark theme)
- Add GitHub Actions workflow
- Add IS_CLOUD detection + inline batch processor
- Update .gitignore for secrets protection
- Add secrets.toml template

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git push origin main
```

Sau khi push, vao https://share.streamlit.io de kich hoat deploy.

---

## Cau truc thu muc cuoi cung

```
content-brief/
├── app.py                      # Streamlit main
├── requirements.txt             # Python deps
├── main_generator.py           # Pipeline
├── worker.py                   # Background (local only)
├── config.py                   # Config
├── modules/                    # All modules
│   ├── content_brief_builder.py
│   ├── koray_analyzer.py
│   ├── markdown_exporter.py
│   ├── internal_linking.py
│   ├── project_manager.py
│   └── ...
├── .streamlit/
│   ├── config.toml             # Theme + server config
│   └── secrets.toml            # API keys (NOT pushed)
├── .github/workflows/
│   └── streamlit-deploy.yml    # CI/CD
├── DEPLOY_STREAMLIT.md         # Huong dan
└── .gitignore                  # Exclude secrets
```

---

## Xem logs tren cloud

Streamlit Cloud tu dong hien thi terminal output cua app.
Vao: App URL → Menu → Help → View logs

---

## Neu gap loi

### Loi: "App crashed"
- Kiem tra `requirements.txt` — thieu package nao
- Kiem tra `app.py` syntax: `python -m py_compile app.py`
- Kiem tra `secrets.toml` tren cloud — API key hop le khong

### Loi: "Module not found"
- `requirements.txt` chua them package do
- Them vao, commit, push

### Loi: "File not found" tren cloud
- Chi duong dan tuong doi (`modules/xxx.py`) trong code
- Khong dung duong dan tuyet doi (`C:\...`)

---

Cap nhat cuoi: 2026-03-26
