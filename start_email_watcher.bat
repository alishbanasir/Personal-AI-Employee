@echo off
cd /d D:\alish-hackathon-0
echo Starting Email Watcher...
echo Monitoring /Approved for email_approval files. Press Ctrl+C to stop.
echo.
.venv\Scripts\python.exe src/email_watcher.py --vault AI_Employee_Vault --watch
pause
