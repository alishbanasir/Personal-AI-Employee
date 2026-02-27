@echo off
cd /d D:\alish-hackathon-0
echo Starting Gmail Watcher...
.venv\Scripts\python.exe src/gmail_watcher.py --vault AI_Employee_Vault
pause
