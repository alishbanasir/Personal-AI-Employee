"""
LinkedIn Watcher — monitors LinkedIn notifications and messages.

Uses Playwright to log in to LinkedIn and scrape new notifications
and unread messages, converting them into .md action files in the vault.

Why Playwright instead of the LinkedIn API?
  LinkedIn's official API restricts inbox/notification access to approved
  Marketing Partners. For personal automation the browser-based approach
  is the only viable option.

Usage:
    python src/linkedin_watcher.py --vault AI_Employee_Vault
    python src/linkedin_watcher.py --vault AI_Employee_Vault --dry-run
    python src/linkedin_watcher.py --vault AI_Employee_Vault --interval 300
    python src/linkedin_watcher.py --vault AI_Employee_Vault --mode notifications
    python src/linkedin_watcher.py --vault AI_Employee_Vault --mode messages
    python src/linkedin_watcher.py --vault AI_Employee_Vault --mode both

Prerequisites:
    1. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env
    2. Install Playwright browsers once:
           playwright install chromium
    3. uv sync  (playwright is already in pyproject.toml dependencies)
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

# How many items to look at per scrape (keeps each cycle fast)
MAX_NOTIFICATIONS = 20
MAX_CONVERSATIONS = 15


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_env(env_file: Path) -> dict:
    """Read a .env file and return key→value dict (does not override os.environ)."""
    result = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _safe_filename(text: str, max_len: int = 40) -> str:
    """Strip special chars and truncate for use in file names."""
    return re.sub(r"[^\w\-]", "_", text)[:max_len].strip("_") or "unknown"


# ── Browser session helpers ───────────────────────────────────────────────────

def _save_session(context, session_path: Path):
    """Persist browser cookies/storage to disk so future runs skip login."""
    state = context.storage_state()
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    logger.info(f"Session saved: {session_path}")


def _login(page, email: str, password: str):
    """Perform interactive login on the LinkedIn login page."""
    logger.info("Logging in to LinkedIn...")
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)

    page.wait_for_selector("#username", timeout=15_000)
    page.fill("#username", email)
    page.fill("#password", password)
    page.click("button[type='submit']")

    # Wait for redirect away from /login — indicates success or security check
    try:
        page.wait_for_url(re.compile(r"linkedin\.com/(?!login)"), timeout=30_000)
        logger.info("Login successful.")
    except Exception:
        # LinkedIn may show a CAPTCHA or verification page
        current = page.url
        if "checkpoint" in current or "challenge" in current:
            logger.warning(
                "LinkedIn is asking for identity verification (CAPTCHA / phone check).\n"
                "  → Open a browser manually, log in once, then re-run this script so\n"
                "    the saved session bypasses the challenge."
            )
            sys.exit(1)
        elif "feed" in current or "mynetwork" in current:
            logger.info("Login redirect detected (feed/mynetwork).")
        else:
            logger.warning(f"Unexpected post-login URL: {current}")


def _build_browser_context(playwright, session_path: Path, headless: bool = True):
    """Launch Chromium and return (browser, context, page)."""
    browser = playwright.chromium.launch(headless=headless)

    if session_path.exists():
        logger.info(f"Loading saved session from {session_path}")
        context = browser.new_context(storage_state=str(session_path))
    else:
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

    page = context.new_page()
    return browser, context, page


def _is_logged_in(page) -> bool:
    """Quick check: are we already on a LinkedIn page as an authenticated user?"""
    try:
        page.goto(f"{LINKEDIN_BASE}/feed/", wait_until="domcontentloaded", timeout=20_000)
        # If we get redirected to /login we are not logged in
        return "login" not in page.url and "authwall" not in page.url
    except Exception:
        return False


# ── Notifications scraper ─────────────────────────────────────────────────────

def _scrape_notifications(page) -> list[dict]:
    """
    Navigate to /notifications/ and return a list of notification dicts.

    Each dict has: id, sender, text, time_str, notification_type, url
    """
    logger.info("Scraping notifications…")
    page.goto(NOTIFICATIONS_URL, wait_until="domcontentloaded", timeout=30_000)

    try:
        # Wait for at least one notification card to appear
        page.wait_for_selector(
            "div[data-urn], .nt-card, [class*='notification-card']",
            timeout=15_000,
        )
    except Exception:
        logger.warning("No notification cards found — page may have changed structure.")
        return []

    notifications = []

    # LinkedIn uses data-urn on notification containers — this is the most stable selector
    cards = page.query_selector_all("div[data-urn]")[:MAX_NOTIFICATIONS]

    for card in cards:
        try:
            urn = card.get_attribute("data-urn") or ""
            if not urn:
                continue

            full_text = card.inner_text().strip()
            if not full_text:
                continue

            # Extract the first line as a pseudo-"sender/subject"
            lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]
            sender_line = lines[0] if lines else "LinkedIn"
            body_text = " ".join(lines[1:]) if len(lines) > 1 else full_text

            # Try to get the notification's own link
            link_el = card.query_selector("a[href]")
            notif_url = ""
            if link_el:
                href = link_el.get_attribute("href") or ""
                notif_url = href if href.startswith("http") else f"{LINKEDIN_BASE}{href}"

            # Rough notification-type detection from text
            text_lower = full_text.lower()
            if "message" in text_lower:
                notif_type = "message"
            elif "connection" in text_lower or "connect" in text_lower:
                notif_type = "connection_request"
            elif "comment" in text_lower:
                notif_type = "comment"
            elif "like" in text_lower or "reacted" in text_lower:
                notif_type = "reaction"
            elif "mention" in text_lower:
                notif_type = "mention"
            elif "job" in text_lower:
                notif_type = "job_alert"
            else:
                notif_type = "notification"

            notifications.append(
                {
                    "id": urn,
                    "sender": sender_line,
                    "text": body_text,
                    "time_str": "",  # LinkedIn shows relative times — not always parseable
                    "notification_type": notif_type,
                    "url": notif_url,
                    "source": "notifications",
                    "raw": full_text[:500],
                }
            )
        except Exception as exc:
            logger.debug(f"Skipping malformed notification card: {exc}")
            continue

    logger.info(f"Found {len(notifications)} notification(s).")
    return notifications


# ── Messages scraper ──────────────────────────────────────────────────────────

def _scrape_messages(page) -> list[dict]:
    """
    Navigate to /messaging/ and return a list of unread message dicts.

    Each dict has: id, sender, subject (preview), body, time_str, url
    """
    logger.info("Scraping messages…")
    page.goto(MESSAGING_URL, wait_until="domcontentloaded", timeout=30_000)

    try:
        page.wait_for_selector(
            "ul.msg-conversations-container__conversations-list li, "
            "[class*='conversation-list'] li, "
            "[data-control-name='overlay.open_conversation']",
            timeout=15_000,
        )
    except Exception:
        logger.warning("No message conversation list found — page structure may have changed.")
        return []

    messages = []

    # Try the most common selector for conversation list items
    conv_items = page.query_selector_all(
        "ul.msg-conversations-container__conversations-list li"
    )

    # Fallback selector if the above returns nothing
    if not conv_items:
        conv_items = page.query_selector_all(
            "[class*='conversation-list-item'], "
            "[data-control-name='overlay.open_conversation']"
        )

    for item in list(conv_items)[:MAX_CONVERSATIONS]:
        try:
            full_text = item.inner_text().strip()
            if not full_text:
                continue

            lines = [ln.strip() for ln in full_text.splitlines() if ln.strip()]

            sender = lines[0] if lines else "Unknown"
            preview = lines[1] if len(lines) > 1 else ""
            time_str = lines[-1] if len(lines) > 2 else ""

            # Generate a stable ID from sender + preview hash
            item_id = f"msg_{_safe_filename(sender)}_{abs(hash(preview)) % 100_000}"

            # Try to get unread indicator
            unread_el = item.query_selector(
                "[class*='unread'], [class*='badge'], [aria-label*='unread']"
            )
            is_unread = unread_el is not None

            # Get the conversation link
            link_el = item.query_selector("a[href]")
            conv_url = ""
            if link_el:
                href = link_el.get_attribute("href") or ""
                conv_url = href if href.startswith("http") else f"{LINKEDIN_BASE}{href}"

            messages.append(
                {
                    "id": item_id,
                    "sender": sender,
                    "subject": preview[:80] if preview else "New message",
                    "body": preview,
                    "time_str": time_str,
                    "is_unread": is_unread,
                    "url": conv_url,
                    "source": "messages",
                    "raw": full_text[:500],
                }
            )
        except Exception as exc:
            logger.debug(f"Skipping malformed conversation item: {exc}")
            continue

    # Only return unread messages (or all if we couldn't detect unread state)
    unread = [m for m in messages if m["is_unread"]]
    result = unread if unread else messages  # fall back to all if unread detection failed
    logger.info(f"Found {len(result)} message(s) (unread detection: {'yes' if unread else 'fallback-all'}).")
    return result


# ── Core watcher class ────────────────────────────────────────────────────────

class LinkedInWatcher:
    def __init__(
        self,
        vault_path: str,
        email: str,
        password: str,
        session_path: str,
        check_interval: int = 300,
        mode: str = "both",
        dry_run: bool = False,
        headless: bool = True,
    ):
        self.vault = Path(vault_path).resolve()
        self.needs_action = self.vault / "Needs_Action"
        self.logs_dir = self.vault / "Logs"
        self.check_interval = check_interval
        self.mode = mode  # "notifications", "messages", or "both"
        self.dry_run = dry_run or os.getenv("DRY_RUN", "false").lower() == "true"
        self.headless = headless

        self.email = email
        self.password = password
        self.session_path = Path(session_path)

        self.needs_action.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # State file — tracks IDs already processed to avoid duplicates across restarts
        self.state_file = self.logs_dir / ".linkedin_seen_ids.json"
        self.seen_ids: set[str] = self._load_seen_ids()

        logger.info(f"Vault        : {self.vault}")
        logger.info(f"Mode         : {self.mode}")
        logger.info(f"Poll interval: {self.check_interval}s")
        logger.info(f"Dry run      : {self.dry_run}")
        logger.info(f"Headless     : {self.headless}")

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_seen_ids(self) -> set[str]:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                ids = set(data.get("seen_ids", []))
                logger.info(f"Loaded {len(ids)} previously-seen item ID(s).")
                return ids
            except (json.JSONDecodeError, KeyError):
                pass
        return set()

    def _save_seen_ids(self):
        self.state_file.write_text(
            json.dumps({"seen_ids": list(self.seen_ids)}, indent=2),
            encoding="utf-8",
        )

    # ── Main poll ─────────────────────────────────────────────────────────────

    def check_for_updates(self) -> list[dict]:
        """Launch Playwright, scrape LinkedIn, return only new unseen items."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error(
                "Playwright is missing. Run:\n"
                "  pip install playwright\n"
                "  playwright install chromium"
            )
            sys.exit(1)

        new_items = []

        with sync_playwright() as pw:
            browser, context, page = _build_browser_context(
                pw, self.session_path, headless=self.headless
            )
            try:
                # Check if the saved session is still valid
                if not _is_logged_in(page):
                    if not self.email or not self.password:
                        logger.error(
                            "Not logged in and no credentials provided.\n"
                            "  Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env"
                        )
                        return []
                    _login(page, self.email, self.password)
                    _save_session(context, self.session_path)

                raw_items = []
                if self.mode in ("notifications", "both"):
                    raw_items.extend(_scrape_notifications(page))
                if self.mode in ("messages", "both"):
                    raw_items.extend(_scrape_messages(page))

                # Filter out already-seen items
                for item in raw_items:
                    if item["id"] not in self.seen_ids:
                        new_items.append(item)
                        self.seen_ids.add(item["id"])

            finally:
                browser.close()

        return new_items

    # ── Action file creation ──────────────────────────────────────────────────

    def create_action_file(self, item: dict) -> Path:
        """Write a LinkedIn_SenderName_Subject.md file to Needs_Action."""
        now = datetime.now()

        safe_sender = _safe_filename(item["sender"], max_len=30)
        subject_text = item.get("subject") or item.get("text") or item["source"]
        safe_subject = _safe_filename(subject_text, max_len=50)
        filename = f"LinkedIn_{safe_sender}_{safe_subject}.md"
        dest = self.needs_action / filename

        # Avoid duplicate files by appending a timestamp suffix
        if dest.exists():
            ts = now.strftime("%H%M%S")
            filename = f"LinkedIn_{safe_sender}_{safe_subject}_{ts}.md"
            dest = self.needs_action / filename

        # Priority heuristics
        text_lower = (item.get("raw", "") + item.get("text", "")).lower()
        priority_keywords = {"urgent", "asap", "invoice", "payment", "deadline", "help"}
        priority = "high" if any(kw in text_lower for kw in priority_keywords) else "medium"

        notif_type = item.get("notification_type", item.get("source", "linkedin"))
        source_url = item.get("url", LINKEDIN_BASE)

        content = f"""---
type: linkedin_{notif_type}
source: linkedin
item_id: "{item['id']}"
sender: "{item['sender'].replace('"', "'")}"
subject: "{subject_text[:80].replace('"', "'")}"
received: {now.strftime('%Y-%m-%d %H:%M')}
priority: {priority}
status: pending
url: {source_url}
---

## LinkedIn {notif_type.replace('_', ' ').title()} Received

**From:** {item['sender']}
**Type:** {notif_type.replace('_', ' ').title()}
**Time:** {item.get('time_str', now.strftime('%Y-%m-%d %H:%M'))}
**Link:** {source_url}

---

## Content

{item.get('raw', item.get('text', item.get('body', '(no content)')))}

---

## Suggested Actions
- [ ] Review LinkedIn {notif_type.replace('_', ' ')} content
- [ ] Determine if a response is required
- [ ] Draft reply if needed (move to Pending_Approval for HITL)
- [ ] Archive or mark as done when complete

## Notes
_Claude: Add analysis and action plan here._
"""

        if self.dry_run:
            logger.info(f"[DRY RUN] Would create: {filename}")
        else:
            dest.write_text(content, encoding="utf-8")
            self._log_action(item, filename, now)
            self._update_dashboard(item, filename, now)

        return dest

    # ── Logging & dashboard ───────────────────────────────────────────────────

    def _log_action(self, item: dict, action_file: str, now: datetime):
        log_file = self.logs_dir / f"{now.strftime('%Y-%m-%d')}.json"
        entry = {
            "timestamp": now.isoformat(),
            "action_type": f"linkedin_{item.get('source', 'item')}_received",
            "actor": "linkedin_watcher",
            "source": item["sender"],
            "subject": item.get("subject") or item.get("text", ""),
            "item_id": item["id"],
            "result_file": action_file,
            "result": "success",
        }
        existing: list = []
        if log_file.exists():
            try:
                existing = json.loads(log_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = []
        existing.append(entry)
        log_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def _update_dashboard(self, item: dict, action_file: str, now: datetime):
        dashboard = self.vault / "Dashboard.md"
        if not dashboard.exists():
            return
        text = dashboard.read_text(encoding="utf-8")
        subject_short = (item.get("subject") or item.get("text", ""))[:40]
        new_row = (
            f"| {now.strftime('%Y-%m-%d %H:%M')} | "
            f"LinkedIn from `{item['sender']}`: _{subject_short}_ → `{action_file}` | ⏳ Pending |"
        )
        marker = "| — | System initialized | ✅ |"
        if marker in text:
            text = text.replace(marker, f"{new_row}\n{marker}")
        else:
            text += f"\n{new_row}\n"
        dashboard.write_text(text, encoding="utf-8")

    # ── Main run loop ─────────────────────────────────────────────────────────

    def run(self):
        logger.info(f"LinkedIn Watcher started (mode={self.mode}, interval={self.check_interval}s)")
        logger.info("Press Ctrl+C to stop.")
        while True:
            try:
                items = self.check_for_updates()
                if items:
                    logger.info(f"Found {len(items)} new LinkedIn item(s).")
                    for item in items:
                        path = self.create_action_file(item)
                        logger.info(f"  → {path.name}")
                    if not self.dry_run:
                        self._save_seen_ids()
                else:
                    logger.debug("No new LinkedIn items.")
            except KeyboardInterrupt:
                logger.info("Stopped by user.")
                break
            except Exception as exc:
                logger.error(f"Poll error: {exc}", exc_info=True)
            time.sleep(self.check_interval)


# ── CLI entry point ───────────────────────────────────────────────────────────

def main():
    # Load .env from project root so env vars are available
    project_root = Path(__file__).parent.parent
    env = _load_env(project_root / ".env")
    for k, v in env.items():
        os.environ.setdefault(k, v)

    parser = argparse.ArgumentParser(
        description="AI Employee LinkedIn Watcher — monitors notifications and messages"
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("VAULT_PATH", "AI_Employee_Vault"),
        help="Absolute path to AI_Employee_Vault directory",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("LINKEDIN_EMAIL", ""),
        help="LinkedIn login email (or set LINKEDIN_EMAIL in .env)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("LINKEDIN_PASSWORD", ""),
        help="LinkedIn login password (or set LINKEDIN_PASSWORD in .env)",
    )
    parser.add_argument(
        "--session",
        default=os.getenv(
            "LINKEDIN_SESSION_PATH",
            str(project_root / ".linkedin_session.json"),
        ),
        help="Path to save/load Playwright browser session (cookies)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("LINKEDIN_POLL_INTERVAL", "300")),
        help="Poll interval in seconds (default: 300 — LinkedIn rate-limits aggressive scrapers)",
    )
    parser.add_argument(
        "--mode",
        choices=["notifications", "messages", "both"],
        default=os.getenv("LINKEDIN_WATCH_MODE", "both"),
        help="What to monitor: notifications, messages, or both (default: both)",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        default=False,
        help="Show the browser window (useful for debugging login / CAPTCHA)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log intended actions without writing files (safe testing mode)",
    )
    args = parser.parse_args()

    if not args.email:
        logger.error(
            "LinkedIn email is required.\n"
            "  Set LINKEDIN_EMAIL in .env or pass --email your@email.com"
        )
        sys.exit(1)

    if not args.password:
        logger.error(
            "LinkedIn password is required.\n"
            "  Set LINKEDIN_PASSWORD in .env or pass --password yourpassword"
        )
        sys.exit(1)

    watcher = LinkedInWatcher(
        vault_path=args.vault,
        email=args.email,
        password=args.password,
        session_path=args.session,
        check_interval=args.interval,
        mode=args.mode,
        dry_run=args.dry_run,
        headless=not args.no_headless,
    )
    watcher.run()


if __name__ == "__main__":
    main()
