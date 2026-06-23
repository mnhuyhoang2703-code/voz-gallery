@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================
echo   Day code len GitHub: voz-gallery
echo ============================================
git --version || (echo [!] Khong tim thay git. Cai Git for Windows truoc. & pause & exit /b 1)
if not exist ".git" git init
git config user.email "mnhuyhoang2703@gmail.com"
git config user.name "mnhuyhoang2703-code"
git add -A
git commit -m "VOZ gallery public deploy"
git branch -M main
git remote remove origin 2>nul
git remote add origin https://github.com/mnhuyhoang2703-code/voz-gallery.git
echo [*] Dang push len GitHub...
git push -u origin main
echo.
echo [*] Xong. Neu thay 'main -> main' la push thanh cong.
pause
