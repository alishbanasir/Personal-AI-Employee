"""
Social Media Manager — LinkedIn automation via Playwright.

HITL Workflow:
  1. Claude (via /draft-linkedin-post skill) drafts a post → saves to /Pending_Approval/
  2. Human reviews the draft → moves file to /Approved/
  3. This script detects the approved file and posts it to LinkedIn

Usage:
    # Scan /Needs_Action for social tasks and print a summary:
    python src/social_media_manager.py --vault AI_Employee_Vault --scan

    # Watch /Approved folder and auto-post when approved files appear:
    python src/social_media_manager.py --vault AI_Employee_Vault --watch

    # Manually execute one specific approved file:
    python src/social_media_manager.py --vault AI_Employee_Vault --post SOCIAL_20260223_linkedin.md

    # Dry run (no actual posting):
    python src/social_media_manager.py --vault AI_Employee_Vault --watch --dry-run
"""
import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Load .env from project root
_ROOT = Path(__file__).parent.parent
_ENV_FILE = _ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SocialMediaManager] %(levelname)s: %(message)s",
)
logger = logging.getLogger("SocialMediaManager")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")
LINKEDIN_SESSION_PATH = os.getenv(
    "LINKEDIN_SESSION_PATH",
    str(_ROOT / ".linkedin_session.json"),
)
LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN = os.getenv("LINKEDIN_PERSON_URN", "")

# Keywords that identify a /Needs_Action file as a social media task
SOCIAL_KEYWORDS = [
    "linkedin",
    "social media",
    "publish post",
    "post on",
    "announce",
    "share on",
    "write a post",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_frontmatter(text: str) -> dict:
    """Extract YAML-style --- frontmatter from a markdown file."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    result: dict = {}
    for line in text[3:end].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


def extract_post_content(text: str) -> str:
    """Extract the post body from an approval .md file.

    Supports both section headers used by the two drafting paths:
      - '## Proposed LinkedIn Post'  (draft_approval_file / social_media_manager)
      - '## Post Content'            (/draft-linkedin-post skill)
    """
    for header in ("## Proposed LinkedIn Post", "## Post Content"):
        match = re.search(
            rf"{re.escape(header)}\s*\n+(.*?)(?=\n---|\n## |\Z)",
            text,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# LinkedIn API Poster (REST API — no browser needed)
# ---------------------------------------------------------------------------

class LinkedInAPIPoster:
    """Posts to LinkedIn via the REST API using an OAuth access token."""

    POSTS_URL = "https://api.linkedin.com/v2/ugcPosts"

    def __init__(self, access_token: str, person_urn: str, dry_run: bool = False):
        self.access_token = access_token
        self.person_urn = person_urn
        self.dry_run = dry_run

    def post(self, content: str) -> bool:
        if self.dry_run:
            logger.info("[DRY RUN] Would post to LinkedIn via API (%d chars)", len(content))
            logger.info("[DRY RUN] Preview:\n%.200s%s", content, "…" if len(content) > 200 else "")
            return True

        try:
            import httpx
        except ImportError:
            logger.error("httpx is not installed. Run: pip install httpx")
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        }
        payload = {
            "author": self.person_urn,
            "lifecycleState": "PUBLISHED",
            "specificContent": {
                "com.linkedin.ugc.ShareContent": {
                    "shareCommentary": {"text": content},
                    "shareMediaCategory": "NONE",
                }
            },
            "visibility": {
                "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
            },
        }

        try:
            resp = httpx.post(self.POSTS_URL, headers=headers, json=payload)
            if resp.status_code in (200, 201):
                logger.info("LinkedIn post published successfully via API.")
                return True
            else:
                logger.error("LinkedIn API error %s: %s", resp.status_code, resp.text)
                return False
        except Exception as exc:
            logger.error("LinkedIn API posting failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# LinkedIn Poster (Playwright)
# ---------------------------------------------------------------------------

class LinkedInPoster:
    """Posts to LinkedIn via a headed Playwright browser session."""

    LOGIN_URL = "https://www.linkedin.com/login"
    FEED_URL = "https://www.linkedin.com/feed/"

    def __init__(self, session_path: str = LINKEDIN_SESSION_PATH, dry_run: bool = False):
        self.session_path = Path(session_path)
        self.dry_run = dry_run

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _launch(self, playwright):
        """Launch a Chromium browser, restoring cookies from disk if available."""
        browser = playwright.chromium.launch(headless=False)  # visible for HITL oversight
        kwargs = {}
        if self.session_path.exists():
            kwargs["storage_state"] = str(self.session_path)
        context = browser.new_context(**kwargs)
        page = context.new_page()
        return browser, context, page

    def _is_logged_in(self, page) -> bool:
        return "feed" in page.url or "/in/" in page.url

    def _login(self, page):
        """Fill email/password and submit; wait for 2FA if LinkedIn requires it."""
        if not LINKEDIN_EMAIL or not LINKEDIN_PASSWORD:
            raise ValueError(
                "Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in your .env file before posting."
            )
        logger.info("Logging in to LinkedIn…")
        page.goto(self.LOGIN_URL)
        page.wait_for_load_state("networkidle")
        page.fill("#username", LINKEDIN_EMAIL)
        page.fill("#password", LINKEDIN_PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # LinkedIn may prompt for CAPTCHA or 2FA — wait up to 2 minutes
        if "challenge" in page.url or "checkpoint" in page.url:
            logger.warning("LinkedIn is requesting additional verification.")
            logger.info("Complete the verification in the browser window (2-minute timeout).")
            page.wait_for_url("**/feed/**", timeout=120_000)

    def _save_session(self, context):
        """Persist cookies so subsequent runs skip the login step."""
        context.storage_state(path=str(self.session_path))
        logger.info(f"Session saved: {self.session_path}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def post(self, content: str) -> bool:
        """
        Publish *content* as a LinkedIn post.
        Returns True on success, False on failure.
        """
        if self.dry_run:
            logger.info("[DRY RUN] Would post to LinkedIn (%d chars)", len(content))
            logger.info("[DRY RUN] Preview:\n%.200s%s", content, "…" if len(content) > 200 else "")
            return True

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright is not installed. Run: playwright install chromium")
            return False

        with sync_playwright() as p:
            browser, context, page = self._launch(p)
            try:
                page.goto(self.FEED_URL)
                page.wait_for_load_state("networkidle")

                if not self._is_logged_in(page):
                    self._login(page)
                    self._save_session(context)

                # ── Open the "Start a post" composer ──────────────────────
                page.wait_for_selector(".share-box-feed-entry__trigger", timeout=15_000)
                page.click(".share-box-feed-entry__trigger")

                # ── Type the post content ──────────────────────────────────
                page.wait_for_selector(".ql-editor", timeout=10_000)
                page.click(".ql-editor")
                page.keyboard.type(content, delay=25)

                # ── Click "Post" ──────────────────────────────────────────
                page.wait_for_selector(
                    "button.share-actions__primary-action:not([disabled])",
                    timeout=10_000,
                )
                page.click("button.share-actions__primary-action")
                page.wait_for_load_state("networkidle")

                logger.info("LinkedIn post published successfully.")
                self._save_session(context)
                return True

            except Exception as exc:
                logger.error("LinkedIn posting failed: %s", exc)
                return False
            finally:
                browser.close()


# ---------------------------------------------------------------------------
# Social Media Manager
# ---------------------------------------------------------------------------

class SocialMediaManager:
    """Manages the full HITL social-media workflow inside the vault."""

    def __init__(self, vault_path: str, dry_run: bool = False):
        self.vault = Path(vault_path).resolve()
        self.dry_run = dry_run or DRY_RUN

        self.needs_action = self.vault / "Needs_Action"
        self.pending_approval = self.vault / "Pending_Approval"
        self.approved = self.vault / "Approved"
        self.rejected = self.vault / "Rejected"
        self.done = self.vault / "Done"
        self.plans = self.vault / "Plans"
        self.logs_dir = self.vault / "Logs"

        if LINKEDIN_ACCESS_TOKEN and LINKEDIN_PERSON_URN:
            logger.info("Using LinkedIn REST API poster.")
            self.poster = LinkedInAPIPoster(LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN, dry_run=self.dry_run)
        else:
            logger.info("Using LinkedIn Playwright poster (no API token found).")
            self.poster = LinkedInPoster(dry_run=self.dry_run)

        # Ensure required folders exist
        for folder in [self.pending_approval, self.approved, self.done, self.logs_dir]:
            folder.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, action_type: str, details: dict):
        log_file = self.logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "actor": "social_media_manager",
            "action_type": action_type,
            **details,
        }
        existing: list = []
        if log_file.exists():
            try:
                existing = json.loads(log_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = []
        existing.append(entry)
        log_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def _is_social_task(self, path: Path) -> bool:
        """Return True if a /Needs_Action file contains a social-media task."""
        text = path.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
        if meta.get("type", "") in ("social_media", "linkedin_post", "social_post"):
            return True
        text_lower = text.lower()
        return any(kw in text_lower for kw in SOCIAL_KEYWORDS)

    def scan_social_tasks(self) -> list[Path]:
        """Return all social-media task files found in /Needs_Action."""
        return [
            f for f in self.needs_action.glob("*.md")
            if f.name != ".gitkeep" and self._is_social_task(f)
        ]

    # ------------------------------------------------------------------
    # Drafting
    # ------------------------------------------------------------------

    def draft_approval_file(self, source_file: Path, post_content: str) -> Path:
        """
        Write a LinkedIn post draft to /Pending_Approval.
        Human reviews by moving the file to /Approved.
        """
        ts = datetime.now()
        ts_str = ts.strftime("%Y%m%d_%H%M%S")
        expires = ts + timedelta(hours=24)
        safe_stem = re.sub(r"[^\w]", "_", source_file.stem)[:30]
        filename = f"SOCIAL_{ts_str}_linkedin_{safe_stem}.md"
        approval_path = self.pending_approval / filename
        char_count = len(post_content)

        content = f"""---
type: social_post_approval
platform: linkedin
action: linkedin_post
created: {ts.isoformat()}
expires: {expires.isoformat()}
status: pending
source_task: {source_file.name}
character_count: {char_count}
---

## Proposed LinkedIn Post

{post_content}

---

## Post Details

- **Platform:** LinkedIn
- **Characters:** {char_count} / 3000
- **Created:** {ts.strftime('%Y-%m-%d %H:%M')}
- **Expires:** {expires.strftime('%Y-%m-%d %H:%M')} (24-hour window)

## Instructions

- To **approve and publish**: Move this file to `/Approved/`
- To **reject**: Move this file to `/Rejected/`

> The post will be published automatically once moved to `/Approved/`.
"""

        if self.dry_run:
            logger.info("[DRY RUN] Would create: Pending_Approval/%s", filename)
            logger.info("[DRY RUN] Preview:\n%.300s", post_content)
            return approval_path

        approval_path.write_text(content, encoding="utf-8")
        logger.info("Approval file created: Pending_Approval/%s", filename)
        self._log("draft_created", {
            "source_task": source_file.name,
            "approval_file": filename,
            "char_count": char_count,
        })
        return approval_path

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_approved_post(self, approved_file: Path) -> bool:
        """
        Read an approved file and publish its post content to LinkedIn.
        Moves the file to /Done on success.
        """
        text = approved_file.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)

        APPROVED_TYPES = {"social_post_approval", "linkedin_post"}
        if meta.get("type") not in APPROVED_TYPES:
            logger.warning("%s has unrecognised type '%s' — skipping.", approved_file.name, meta.get("type"))
            return False

        if meta.get("platform", "linkedin") != "linkedin":
            logger.warning("Platform '%s' not supported yet — skipping.", meta.get("platform"))
            return False

        post_content = extract_post_content(text)
        if not post_content:
            logger.error("Could not extract post content from %s", approved_file.name)
            return False

        logger.info("Executing approved post: %s", approved_file.name)
        logger.info("Preview: %.120s…", post_content)

        success = self.poster.post(post_content)

        if success:
            if not self.dry_run:
                dest = self.done / approved_file.name
                shutil.move(str(approved_file), str(dest))
                logger.info("Moved to /Done: %s", approved_file.name)
            self._log("linkedin_post_published", {
                "file": approved_file.name,
                "char_count": len(post_content),
                "status": "success",
            })
        else:
            logger.error("Failed to publish %s", approved_file.name)
            self._log("linkedin_post_failed", {
                "file": approved_file.name,
                "status": "failed",
            })

        return success


# ---------------------------------------------------------------------------
# Watchdog handler for /Approved folder
# ---------------------------------------------------------------------------

class ApprovedFolderHandler(FileSystemEventHandler):
    """Triggers LinkedIn posting whenever a social-post approval file lands in /Approved."""

    def __init__(self, manager: SocialMediaManager):
        self.manager = manager

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix != ".md" or path.name == ".gitkeep":
            return

        logger.info("New file in /Approved: %s", path.name)
        time.sleep(0.5)  # give OS time to finish writing

        try:
            meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            return

        if meta.get("type") in ("social_post_approval", "linkedin_post"):
            self.manager.execute_approved_post(path)
        else:
            logger.info("%s is not a social-post approval — skipping.", path.name)


def run_watcher(manager: SocialMediaManager):
    """Watch /Approved indefinitely; post to LinkedIn when approval files arrive."""
    handler = ApprovedFolderHandler(manager)
    observer = Observer()
    observer.schedule(handler, str(manager.approved), recursive=False)
    observer.start()
    logger.info("Watching /Approved for LinkedIn posts. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    logger.info("Watcher stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Social Media Manager — LinkedIn HITL automation"
    )
    parser.add_argument("--vault", required=True, help="Path to AI_Employee_Vault")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without posting")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--scan",
        action="store_true",
        help="Scan /Needs_Action for social media tasks",
    )
    group.add_argument(
        "--watch",
        action="store_true",
        help="Watch /Approved folder and post approved items",
    )
    group.add_argument(
        "--post",
        metavar="FILENAME",
        help="Immediately execute a specific approved file (must be in /Approved/)",
    )

    args = parser.parse_args()
    manager = SocialMediaManager(args.vault, dry_run=args.dry_run)

    if args.scan:
        tasks = manager.scan_social_tasks()
        if not tasks:
            logger.info("No social media tasks found in /Needs_Action.")
        else:
            logger.info("Found %d social task(s) in /Needs_Action:", len(tasks))
            for t in tasks:
                logger.info("  → %s", t.name)
            logger.info("Run /draft-linkedin-post in Claude Code to draft posts.")

    elif args.watch:
        run_watcher(manager)

    elif args.post:
        approved_file = manager.approved / args.post
        if not approved_file.exists():
            logger.error("File not found in /Approved: %s", args.post)
            sys.exit(1)
        success = manager.execute_approved_post(approved_file)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
