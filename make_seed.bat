@echo off
cd /d "%~dp0"
echo [*] Dang xuat database -> seed.json ...
.venv\Scripts\python export_seed.py
echo.
pause
