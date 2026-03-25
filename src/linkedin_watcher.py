"""
LinkedIn Watcher — monitors LinkedIn notifications and messages.
Updated with Dashboard & Logging logic for a complete AI Vault experience.
"""
import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [LinkedInWatcher] %(levelname)s: %(message)s",
)
logger = logging.getLogger("LinkedInWatcher")

# ── Constants ─────────────────────────────────────────────────────────────────

LINKEDIN_BASE = "https://www.linkedin.com"
NOTIFICATIONS_URL = f"{LINKEDIN_BASE}/notifications/"
MESSAGING_URL = f"{LINKEDIN_BASE}/messaging/"
LOGIN_URL = f"{LINKEDIN_BASE}/login"

MAX_NOTIFICATIONS = 20
MAX_CONVERSATIONS = 15

# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_env(env_file: Path) -> dict:
    result = {}
    if not env_file.exists(): return result
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result

def _safe_filename(text: str, max_len: int = 40) -> str:
    return re.sub(r"[^\w\-]", "_", text)[:max_len].strip("_") or "unknown"

# ── Browser session helpers ───────────────────────────────────────────────────

def _save_session(context, session_path: Path):
    state = context.storage_state()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    logger.info(f"Session saved: {session_path}")

def _login(page, email: str, password: str):
    if "feed" in page.url:
        logger.info("Already on feed, bypassing login selectors.")
        return
    logger.info("Logging in to LinkedIn...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(3000)
    # LinkedIn uses either #username or input[name='session_key']
    username_sel = "#username, input[name='session_key'], input[autocomplete='username']"
    password_sel = "#password, input[name='session_password'], input[type='password']"
    # If LinkedIn redirected us to feed, we're already logged in
    if "feed" in page.url or ("login" not in page.url and "authwall" not in page.url):
        logger.info("Already logged in (redirected away from login page).")
        return
    try:
        page.wait_for_selector(username_sel, timeout=20_000)
    except Exception:
        logger.error(f"Login page did not load expected fields. Current URL: {page.url}")
        sys.exit(1)
    page.fill(username_sel, email)
    page.fill(password_sel, password)
    page.click("button[type='submit']")
    try:
        page.wait_for_url(re.compile(r"linkedin\.com/(?!login)"), timeout=30_000)
        logger.info("Login successful.")
    except Exception:
        if "checkpoint" in page.url or "challenge" in page.url:
            logger.warning("Verification detected. Run with --no-headless to solve it once.")
            sys.exit(1)

def _build_browser_context(playwright, session_path: Path, headless: bool = True):
    browser = playwright.chromium.launch(headless=headless)
    if session_path.exists():
        logger.info(f"Loading session: {session_path}")
        context = browser.new_context(storage_state=str(session_path))
    else:
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
    return browser, context, context.new_page()

def _is_logged_in(page) -> bool:
    try:
        page.goto(f"{LINKEDIN_BASE}/feed/", wait_until="domcontentloaded", timeout=20_000)
        page.wait_for_timeout(2000)
        url = page.url
        if "login" in url or "authwall" in url or "signup" in url:
            return False
        return "feed" in url or "linkedin.com/in/" in url
    except Exception:
        return False

# ── Scrapers ──────────────────────────────────────────────────────────────────

def _scrape_notifications(page) -> list[dict]:
    logger.info("Scraping notifications…")
    page.goto(NOTIFICATIONS_URL, wait_until="networkidle", timeout=30_000)
    sel = "div[data-urn], .nt-card, .notification-item, article[data-urn]"
    try: page.wait_for_selector(sel, timeout=15_000)
    except: return []
    
    notifications = []
    for card in page.query_selector_all(sel)[:MAX_NOTIFICATIONS]:
        try:
            full_text = card.inner_text().strip()
            if not full_text: continue
            urn = card.get_attribute("data-urn") or str(hash(full_text))
            notifications.append({
                "id": urn, "sender": full_text.splitlines()[0], "text": " ".join(full_text.splitlines()),
                "source": "notifications", "raw": full_text[:500]
            })
        except: continue
    return notifications

def _scrape_messages(page) -> list[dict]:
    logger.info("Scraping messages…")
    page.goto(MESSAGING_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_timeout(5000)  # 5 seconds wait taake UI render ho jaye
    message_item_selector = ".msg-conversation-listitem, [class*='msg-conversations-container'] li"
    try: page.wait_for_selector(message_item_selector, timeout=15_000)
    except: return []

    messages = []
    for item in page.query_selector_all(message_item_selector)[:MAX_CONVERSATIONS]:
        try:
            txt = item.inner_text().strip()
            if not txt: continue
            unread = item.query_selector("[class*='unread'], .notification-badge") is not None
            messages.append({
                "id": f"msg_{hash(txt)}", "sender": txt.splitlines()[0], "subject": txt.splitlines()[1] if len(txt.splitlines())>1 else "New Msg",
                "is_unread": unread, "source": "messages", "raw": txt[:500]
            })
        except: continue
    unread_only = [m for m in messages if m["is_unread"]]
    return unread_only if unread_only else messages

# ── Watcher Core ──────────────────────────────────────────────────────────────

class LinkedInWatcher:
    def __init__(self, vault_path, email, password, session_path, check_interval=300, mode="both", dry_run=False, headless=True):
        self.vault = Path(vault_path).resolve()
        self.needs_action, self.logs_dir = self.vault / "Needs_Action", self.vault / "Logs"
        self.check_interval, self.mode, self.dry_run, self.headless = check_interval, mode, dry_run, headless
        self.email, self.password, self.session_path = email, password, Path(session_path)
        
        for d in [self.needs_action, self.logs_dir]: d.mkdir(parents=True, exist_ok=True)
        self.state_file = self.logs_dir / ".linkedin_seen_ids.json"
        self.seen_ids = self._load_seen_ids()

    def _load_seen_ids(self):
        if self.state_file.exists():
            try: return set(json.loads(self.state_file.read_text())["seen_ids"])
            except: pass
        return set()

    def _save_seen_ids(self):
        self.state_file.write_text(json.dumps({"seen_ids": list(self.seen_ids)}, indent=2))

    def _update_dashboard(self, item, filename, now):
        dash = self.vault / "Dashboard.md"
        if not dash.exists(): return
        content = dash.read_text(encoding="utf-8")
        row = f"| {now.strftime('%Y-%m-%d %H:%M')} | LinkedIn from `{item['sender']}` → `{filename}` | ⏳ Pending |"
        dash.write_text(content + f"\n{row}\n", encoding="utf-8")

    def create_action_file(self, item):
        now = datetime.now()
        safe_sender = _safe_filename(item["sender"], 30)
        filename = f"LinkedIn_{safe_sender}_{now.strftime('%H%M%S')}.md"
        dest = self.needs_action / filename
        content = f"---\ntype: linkedin_action\nsender: \"{item['sender']}\"\nreceived: {now.isoformat()}\nstatus: pending\n---\n## Content\n{item['raw']}"
        if not self.dry_run:
            dest.write_text(content, encoding="utf-8")
            self._update_dashboard(item, filename, now)
        return dest

    def run(self):
        logger.info(f"LinkedIn Watcher Running... Mode: {self.mode}")
        while True:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    browser, context, page = _build_browser_context(pw, self.session_path, self.headless)
                    if not _is_logged_in(page):
                        _login(page, self.email, self.password)
                        _save_session(context, self.session_path)
                    
                    found = []
                    if self.mode in ("notifications", "both"): found.extend(_scrape_notifications(page))
                    if self.mode in ("messages", "both"): found.extend(_scrape_messages(page))

                    new_paths = []
                    for item in found:
                        if item["id"] not in self.seen_ids:
                            path = self.create_action_file(item)
                            logger.info(f"New Item: {path.name}")
                            self.seen_ids.add(item["id"])
                            new_paths.append(path)
                    self._save_seen_ids()
                    browser.close()

                    # ── Trigger Analyzer on new items ──────────────────────
                    if new_paths and not self.dry_run:
                        self._run_analyzer(new_paths)

            except Exception as e: logger.error(f"Error: {e}")
            time.sleep(self.check_interval)

    def _run_analyzer(self, new_paths: list):
        """Import and run the Analyzer on newly scraped files."""
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from analyzer import Analyzer
            analyzer = Analyzer(str(self.vault), dry_run=self.dry_run)
            analyzer.process_all(file_list=[str(p) for p in new_paths])
        except ImportError:
            logger.warning("analyzer.py not found — skipping auto-analysis.")
        except Exception as e:
            logger.error(f"Analyzer error: {e}")

def main():
    root = Path(__file__).parent.parent
    env = _load_env(root / ".env")
    for k, v in env.items(): os.environ.setdefault(k, v)
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument("--email", default=os.getenv("LINKEDIN_EMAIL", ""))
    parser.add_argument("--password", default=os.getenv("LINKEDIN_PASSWORD", ""))
    parser.add_argument("--interval", type=int, default=300)
    parser.add_argument("--no-headless", action="store_true")
    args = parser.parse_args()

    watcher = LinkedInWatcher(
        args.vault, args.email, args.password, root / ".linkedin_session.json",
        args.interval, headless=not args.no_headless
    )
    watcher.run()

if __name__ == "__main__":
    main()