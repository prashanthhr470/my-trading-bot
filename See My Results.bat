@echo off
cd /d "%~dp0"
start "HAFNOT Live Updater" /MIN .venv\Scripts\python.exe hafnot_live_dashboard.py
timeout /t 2 /nobreak >nul
start "" "MY_RESULTS.html"
