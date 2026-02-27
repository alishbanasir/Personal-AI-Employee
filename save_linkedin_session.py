"""
Run this script directly in your terminal to log in to LinkedIn manually
and save the browser session for future automated posts.

Usage:
    .venv/Scripts/python.exe save_linkedin_session.py
"""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

SESSION_PATH = Path(__file__).parent / ".linkedin_session.json"

print("=" * 60)
print("  LinkedIn Session Saver")
print("=" * 60)
print()
print("1. A browser window will open LinkedIn's login page.")
print("2. Log in manually (email, password, 2FA if needed).")
print("3. Once you see your feed, the session is saved automatically.")
print()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.linkedin.com/login")

    print("Browser opened. Waiting for you to reach the feed...")
    print("(You have 5 minutes)")
    print()

    for i in range(300):
        time.sleep(1)
        try:
            url = page.url
            if "/feed" in url or "/in/" in url:
                print(f"Feed detected! Saving session...")
                time.sleep(2)
                context.storage_state(path=str(SESSION_PATH))
                print(f"Session saved to: {SESSION_PATH}")
                print()
                print("You can now close this window and run:")
                print("  .venv/Scripts/python.exe src/social_media_manager.py "
                      "--vault AI_Employee_Vault "
                      "--post linkedin_post_20260223_ai_employee_hackathon0.md")
                break
        except Exception as e:
            print(f"Error checking URL: {e}")
            break
    else:
        print("Timed out. Please run the script again and log in within 5 minutes.")

    input("\nPress Enter to close the browser...")
    browser.close()
