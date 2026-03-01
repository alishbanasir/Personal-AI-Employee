"""
Twitter/X Poster — HITL automation via the Twitter API v2 (tweepy).

HITL Workflow:
  1. Claude (or a skill) drafts a tweet → saves to /Pending_Approval/
  2. Human reviews the draft → moves file to /Approved/
  3. This script detects the approved file, posts it to Twitter/X, and moves
     the file to /Done/

Usage:
    # Watch /Approved folder and auto-post when approved files appear:
    python src/twitter_poster.py --vault AI_Employee_Vault --watch

    # Manually execute one specific approved file:
    python src/twitter_poster.py --vault AI_Employee_Vault --post TWITTER_20260301_120000.md

    # Dry run (no actual posting):
    python src/twitter_poster.py --vault AI_Employee_Vault --watch --dry-run

Required .env keys:
    TWITTER_API_KEY
    TWITTER_API_SECRET
    TWITTER_ACCESS_TOKEN
    TWITTER_ACCESS_TOKEN_SECRET
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

# ---------------------------------------------------------------------------
# Bootstrap: load .env from project root
# ---------------------------------------------------------------------------

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
    format="%(asctime)s [TwitterPoster] %(levelname)s: %(message)s",
)
logger = logging.getLogger("TwitterPoster")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

TWITTER_API_KEY = os.getenv("TWITTER_API_KEY", "")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET", "")

TWEET_MAX_CHARS = 280


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


def extract_tweet_content(text: str) -> str:
    """Extract the tweet body from an approval .md file.

    Looks for a '## Post Content' or '## Tweet Content' section.
    """
    for header in ("## Tweet Content", "## Post Content"):
        match = re.search(
            rf"{re.escape(header)}\s*\n+(.*?)(?=\n---|\n## |\Z)",
            text,
            re.DOTALL,
        )
        if match:
            return match.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# Twitter API Poster
# ---------------------------------------------------------------------------


class TwitterPoster:
    """Posts to Twitter/X via the API v2 using tweepy."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run

    def _get_client(self):
        """Return an authenticated tweepy.Client (API v2)."""
        try:
            import tweepy  # type: ignore
        except ImportError:
            raise ImportError(
                "tweepy is not installed. Run: uv add tweepy  (or pip install tweepy)"
            )

        missing = [
            name
            for name, val in [
                ("TWITTER_API_KEY", TWITTER_API_KEY),
                ("TWITTER_API_SECRET", TWITTER_API_SECRET),
                ("TWITTER_ACCESS_TOKEN", TWITTER_ACCESS_TOKEN),
                ("TWITTER_ACCESS_TOKEN_SECRET", TWITTER_ACCESS_TOKEN_SECRET),
            ]
            if not val
        ]
        if missing:
            raise ValueError(
                f"Missing Twitter credentials in .env: {', '.join(missing)}"
            )

        return tweepy.Client(
            consumer_key=TWITTER_API_KEY,
            consumer_secret=TWITTER_API_SECRET,
            access_token=TWITTER_ACCESS_TOKEN,
            access_token_secret=TWITTER_ACCESS_TOKEN_SECRET,
        )

    def post(self, content: str) -> bool:
        """
        Publish *content* as a tweet.
        Returns True on success, False on failure.
        """
        if len(content) > TWEET_MAX_CHARS:
            logger.warning(
                "Tweet is %d chars (max %d). It will be truncated by the API.",
                len(content),
                TWEET_MAX_CHARS,
            )

        if self.dry_run:
            logger.info("[DRY RUN] Would post to Twitter/X (%d chars)", len(content))
            logger.info(
                "[DRY RUN] Preview:\n%.280s%s",
                content,
                "…" if len(content) > 280 else "",
            )
            return True

        try:
            client = self._get_client()
            response = client.create_tweet(text=content)
            tweet_id = response.data["id"]
            logger.info("Tweet published successfully. Tweet ID: %s", tweet_id)
            return True
        except ImportError as exc:
            logger.error("%s", exc)
            return False
        except ValueError as exc:
            logger.error("Configuration error: %s", exc)
            return False
        except Exception as exc:
            logger.error("Twitter posting failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Twitter Post Manager (vault workflow)
# ---------------------------------------------------------------------------


class TwitterPostManager:
    """Manages the full HITL Twitter posting workflow inside the vault."""

    def __init__(self, vault_path: str, dry_run: bool = False):
        self.vault = Path(vault_path).resolve()
        self.dry_run = dry_run or DRY_RUN

        self.pending_approval = self.vault / "Pending_Approval"
        self.approved = self.vault / "Approved"
        self.done = self.vault / "Done"
        self.logs_dir = self.vault / "Logs"

        self.poster = TwitterPoster(dry_run=self.dry_run)

        for folder in [self.pending_approval, self.approved, self.done, self.logs_dir]:
            folder.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, action_type: str, details: dict):
        log_file = self.logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "actor": "twitter_poster",
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
    # Drafting (helper for creating approval files programmatically)
    # ------------------------------------------------------------------

    def draft_approval_file(self, tweet_content: str, source_name: str = "manual") -> Path:
        """
        Write a Twitter post draft to /Pending_Approval.
        Human approves by moving the file to /Approved/.
        """
        ts = datetime.now()
        ts_str = ts.strftime("%Y%m%d_%H%M%S")
        expires = ts + timedelta(hours=24)
        char_count = len(tweet_content)
        filename = f"TWITTER_{ts_str}.md"
        approval_path = self.pending_approval / filename

        content = f"""---
type: twitter_post
platform: twitter
created: {ts.isoformat()}
expires: {expires.isoformat()}
status: pending
source: {source_name}
character_count: {char_count}
---

## Tweet Content

{tweet_content}

---

## Post Details

- **Platform:** Twitter/X
- **Characters:** {char_count} / {TWEET_MAX_CHARS}
- **Created:** {ts.strftime('%Y-%m-%d %H:%M')}
- **Expires:** {expires.strftime('%Y-%m-%d %H:%M')} (24-hour window)

## Instructions

- To **approve and publish**: Move this file to `/Approved/`
- To **reject**: Move this file to `/Rejected/`

> The tweet will be published automatically once moved to `/Approved/`.
"""

        if self.dry_run:
            logger.info("[DRY RUN] Would create: Pending_Approval/%s", filename)
            logger.info("[DRY RUN] Preview:\n%.280s", tweet_content)
            return approval_path

        approval_path.write_text(content, encoding="utf-8")
        logger.info("Approval file created: Pending_Approval/%s", filename)
        self._log("twitter_draft_created", {
            "approval_file": filename,
            "char_count": char_count,
            "source": source_name,
        })
        return approval_path

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute_approved_post(self, approved_file: Path) -> bool:
        """
        Read an approved file, post its tweet content to Twitter/X,
        and move the file to /Done on success.
        Returns True on success, False on failure.
        """
        text = approved_file.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)

        if meta.get("type") != "twitter_post":
            logger.warning(
                "%s has type '%s' — not a twitter_post, skipping.",
                approved_file.name,
                meta.get("type"),
            )
            return False

        if meta.get("platform", "twitter") != "twitter":
            logger.warning(
                "Platform '%s' not supported by this poster — skipping.",
                meta.get("platform"),
            )
            return False

        tweet_content = extract_tweet_content(text)
        if not tweet_content:
            logger.error("Could not extract tweet content from %s", approved_file.name)
            return False

        logger.info("Executing approved tweet: %s", approved_file.name)
        logger.info("Preview: %.120s%s", tweet_content, "…" if len(tweet_content) > 120 else "")

        success = self.poster.post(tweet_content)

        if success:
            if not self.dry_run:
                dest = self.done / approved_file.name
                shutil.move(str(approved_file), str(dest))
                logger.info("Moved to /Done: %s", approved_file.name)
            self._log("twitter_post_published", {
                "file": approved_file.name,
                "char_count": len(tweet_content),
                "status": "success",
            })
        else:
            logger.error("Failed to publish %s", approved_file.name)
            self._log("twitter_post_failed", {
                "file": approved_file.name,
                "status": "failed",
            })

        return success

    def process_existing(self):
        """Post any twitter_post approval files already sitting in /Approved at startup."""
        pending = [f for f in self.approved.glob("*.md") if f.name != ".gitkeep"]
        if not pending:
            logger.info("No existing files in /Approved at startup.")
            return
        logger.info("Processing %d existing file(s) in /Approved...", len(pending))
        for f in pending:
            try:
                meta = parse_frontmatter(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if meta.get("type") == "twitter_post":
                self.execute_approved_post(f)
            else:
                logger.debug("%s is not a twitter_post — skipping.", f.name)


# ---------------------------------------------------------------------------
# Watchdog handler for /Approved folder
# ---------------------------------------------------------------------------


class ApprovedTwitterHandler(FileSystemEventHandler):
    """Triggers Twitter posting whenever a twitter_post approval file lands in /Approved."""

    def __init__(self, manager: TwitterPostManager):
        self.manager = manager

    def _handle(self, path: Path):
        if path.suffix != ".md" or path.name == ".gitkeep":
            return

        logger.info("New file in /Approved: %s", path.name)
        time.sleep(0.5)  # give the OS time to finish writing

        try:
            meta = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            return

        if meta.get("type") == "twitter_post":
            self.manager.execute_approved_post(path)
        else:
            logger.info("%s is not a twitter_post — skipping.", path.name)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(Path(event.src_path))

    # Also handle moves into the folder (e.g. Obsidian drag-and-drop)
    def on_moved(self, event):
        if not event.is_directory:
            self._handle(Path(event.dest_path))


def run_watcher(manager: TwitterPostManager):
    """Watch /Approved indefinitely; post to Twitter/X when approval files arrive."""
    manager.process_existing()

    handler = ApprovedTwitterHandler(manager)
    observer = Observer()
    observer.schedule(handler, str(manager.approved), recursive=False)
    observer.start()
    logger.info("Watching /Approved for Twitter posts. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    logger.info("Twitter poster stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Twitter/X Poster — HITL automation for the AI Employee vault"
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("VAULT_PATH", "AI_Employee_Vault"),
        help="Path to AI_Employee_Vault directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Simulate without posting (safe testing mode)",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--watch",
        action="store_true",
        help="Watch /Approved folder and post approved tweets automatically",
    )
    group.add_argument(
        "--post",
        metavar="FILENAME",
        help="Immediately execute a specific approved file (must be in /Approved/)",
    )
    group.add_argument(
        "--draft",
        metavar="TEXT",
        help="Create a draft approval file for the given tweet text",
    )

    args = parser.parse_args()
    manager = TwitterPostManager(args.vault, dry_run=args.dry_run)

    if args.watch:
        run_watcher(manager)

    elif args.post:
        approved_file = manager.approved / args.post
        if not approved_file.exists():
            logger.error("File not found in /Approved: %s", args.post)
            sys.exit(1)
        success = manager.execute_approved_post(approved_file)
        sys.exit(0 if success else 1)

    elif args.draft:
        path = manager.draft_approval_file(args.draft)
        logger.info("Draft saved: %s", path)


if __name__ == "__main__":
    main()
