@echo off
chcp 65001 >nul
title Content Brief AI - Startup
echo ===================================================
echo     KHOI DONG CONTENT BRIEF GENERATOR TOOL
echo ===================================================
echo.

:: 1. Chạy Worker ngầm trong một cửa sổ cmd riêng biệt
echo [1/2] Dang khoi dong Background Worker...
start "Content Brief Worker" cmd /c "python worker.py"

:: Delay một chút để worker khởi động
timeout /t 2 /nobreak >nul

:: 2. Chạy Streamlit UI ở cửa sổ hiện tại
echo [2/2] Dang khoi dong giao dien Streamlit...
echo Vui long cho trong giay lat, trinh duyet se tu dong mo len.
echo.
python -m streamlit run app.py

pause
