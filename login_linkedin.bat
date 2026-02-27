@echo off
echo ============================================
echo   LinkedIn Session Saver
echo ============================================
echo.
echo A browser will open. Click "Sign in with Google",
echo complete login, and wait for your feed to load.
echo The session will save automatically.
echo.
cd /d D:\alish-hackathon-0
.venv\Scripts\python.exe save_linkedin_session.py
echo.
pause
