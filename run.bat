@echo off
chcp 65001 >nul
cd /d "%~dp0"
title VOZ Gallery + Swipe

echo ============================================
echo   VOZ Image Gallery + Swipe
echo ============================================

REM --- Tao venv neu chua co ---
if not exist ".venv\Scripts\python.exe" (
  echo [*] Tao moi truong ao...
  python -m venv .venv
  if errorlevel 1 (
    echo [!] Khong tao duoc venv. Kiem tra Python da cai chua: python --version
    pause
    exit /b 1
  )
)
call ".venv\Scripts\activate.bat"

REM --- Cai thu vien, ghi log ra install.log ---
echo [*] Cai thu vien... (chi tiet trong install.log)
python -m pip install --upgrade pip  > install.log 2>&1
python -m pip install -r requirements-local.txt  >> install.log 2>&1
if errorlevel 1 (
  echo.
  echo [!] CAI DAT THAT BAI. Mo file install.log de xem loi chi tiet.
  pause
  exit /b 1
)

REM --- Pillow de tao thumbnail (khong bat buoc; loi cung khong sao) ---
python -m pip install pillow >> install.log 2>&1

REM --- Mo trinh duyet sau 4 giay (cho server khoi dong) ---
start "" /b cmd /c "timeout /t 4 >nul & explorer http://127.0.0.1:8000"

echo.
echo [*] Server chay tai: http://127.0.0.1:8000   (Bam Ctrl+C de dung)
echo.
python server.py
echo.
echo [!] Server da dung. Neu co loi o tren, chup man hinh gui lai.
pause
