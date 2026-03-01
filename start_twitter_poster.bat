@echo off
REM Twitter/X Poster — double-click to start watching /Approved for tweet approvals
REM Requires TWITTER_API_KEY, TWITTER_API_SECRET, TWITTER_ACCESS_TOKEN,
REM          TWITTER_ACCESS_TOKEN_SECRET in .env

cd /d "%~dp0"
echo Starting Twitter/X Poster...
python src\twitter_poster.py --vault AI_Employee_Vault --watch
pause
