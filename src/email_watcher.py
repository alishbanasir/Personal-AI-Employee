"""
Email Watcher — monitors /Approved for email_approval .md files and sends them.

HITL Workflow:
  1. Claude (via draft_email MCP tool) drafts an email → saves to /Pending_Approval/
  2. Human reviews the draft → moves file to /Approved/
  3. This script detects the approved file, sends it via Gmail, and moves it to /Done/

Usage:
    # Watch /Approved folder and auto-send when email approval files appear:
    python src/email_watcher.py --vault AI_Employee_Vault --watch

    # Manually send one specific approved file:
    python src/email_watcher.py --vault AI_Employee_Vault --send EMAIL_20260226_162727_MCP_Server_Test.md

    # Dry run (no actual sending):
    python src/email_watcher.py --vault AI_Employee_Vault --watch --dry-run
"""
import argparse
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
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
    format="%(asctime)s [EmailWatcher] %(levelname)s: %(message)s",
)
logger = logging.getLogger("EmailWatcher")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict:
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


def _extract_body(text: str) -> str:
    """Extract the plain-text email body from an email_approval .md file.

    The body lives between the second '---' separator and the '## Instructions'
    footer, with the To/Subject header lines stripped out.
    """
    parts = text.split("---")
    # parts[0] = '', parts[1] = frontmatter, parts[2+] = body section
    body_section = "---".join(parts[2:]) if len(parts) > 2 else ""

    # Drop the instruction footer
    if "## Instructions" in body_section:
        body_section = body_section[: body_section.index("## Instructions")]

    # The body is everything after the first inner '---' separator
    lines = body_section.splitlines()
    body_lines: list[str] = []
    past_header = False
    for line in lines:
        if line.strip() == "---" and not past_header:
            past_header = True
            continue
        if past_header:
            body_lines.append(line)

    return "\n".join(body_lines).strip()


# ---------------------------------------------------------------------------
# Email sender manager
# ---------------------------------------------------------------------------

class EmailWatcher:
    """Manages the full HITL email-send workflow inside the vault."""

    def __init__(self, vault_path: str, dry_run: bool = False):
        self.vault = Path(vault_path).resolve()
        self.dry_run = dry_run or DRY_RUN

        self.approved = self.vault / "Approved"
        self.done = self.vault / "Done"
        self.logs_dir = self.vault / "Logs"

        for folder in [self.approved, self.done, self.logs_dir]:
            folder.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, action_type: str, details: dict):
        log_file = self.logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "actor": "email_watcher",
            "action_type": action_type,
            **details,
        }
        existing: list = []
        if log_file.exists():
            try:
                existing = json.loads(log_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        existing.append(entry)
        log_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_approved_email(self, approved_file: Path) -> bool:
        """
        Read an approved email file, send it via Gmail, and move to /Done.
        Returns True on success, False on failure.
        """
        text = approved_file.read_text(encoding="utf-8")
        meta = _parse_frontmatter(text)

        if meta.get("type") != "email_approval":
            logger.warning(
                "%s has type '%s' — not an email approval, skipping.",
                approved_file.name, meta.get("type"),
            )
            return False

        to = meta.get("to", "").strip()
        subject = meta.get("subject", "").strip()
        cc = meta.get("cc", "").strip()
        reply_to = meta.get("reply_to", "").strip()

        if not to or not subject:
            logger.error("Missing 'to' or 'subject' in %s — skipping.", approved_file.name)
            return False

        body = _extract_body(text)
        if not body:
            logger.error("Could not extract email body from %s — skipping.", approved_file.name)
            return False

        logger.info("Sending email: '%s' → %s", subject, to)

        if self.dry_run:
            logger.info("[DRY RUN] Would send email to %s | Subject: %s", to, subject)
            logger.info("[DRY RUN] Body preview: %.150s", body)
            self._log("email_dry_run", {
                "file": approved_file.name,
                "to": to,
                "subject": subject,
            })
            return True

        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from gmail_sender import send_email  # type: ignore

            result = send_email(to=to, subject=subject, body=body, cc=cc, reply_to=reply_to)
            message_id = result.get("message_id")
            logger.info("Email sent! Gmail Message ID: %s", message_id)

            # Move to Done
            dest = self.done / approved_file.name
            shutil.move(str(approved_file), str(dest))
            logger.info("Moved to /Done: %s", approved_file.name)

            self._log("email_sent", {
                "file": approved_file.name,
                "to": to,
                "subject": subject,
                "message_id": message_id,
            })
            return True

        except ImportError:
            logger.error(
                "Gmail packages not installed. Run: uv sync --extra gmail"
            )
            return False
        except Exception as exc:
            logger.error("Failed to send %s: %s", approved_file.name, exc)
            self._log("email_failed", {
                "file": approved_file.name,
                "to": to,
                "subject": subject,
                "error": str(exc),
            })
            return False

    def process_existing(self):
        """Send any email approval files already sitting in /Approved at startup."""
        pending = [
            f for f in self.approved.glob("*.md")
            if f.name != ".gitkeep"
        ]
        if not pending:
            logger.info("No existing files in /Approved at startup.")
            return
        logger.info("Processing %d existing file(s) in /Approved...", len(pending))
        for f in pending:
            try:
                meta = _parse_frontmatter(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if meta.get("type") == "email_approval":
                self.send_approved_email(f)
            else:
                logger.debug("%s is not an email approval — skipping.", f.name)


# ---------------------------------------------------------------------------
# Watchdog handler
# ---------------------------------------------------------------------------

class ApprovedEmailHandler(FileSystemEventHandler):
    """Triggers email sending whenever an email_approval file lands in /Approved."""

    def __init__(self, watcher: EmailWatcher):
        self.watcher = watcher

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix != ".md" or path.name == ".gitkeep":
            return

        logger.info("New file in /Approved: %s", path.name)
        time.sleep(0.5)  # give OS time to finish writing the file

        try:
            meta = _parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            return

        if meta.get("type") == "email_approval":
            self.watcher.send_approved_email(path)
        else:
            logger.info("%s is not an email approval — skipping.", path.name)

    # Also handle moves into the folder (e.g. from Obsidian drag-and-drop)
    on_moved = on_created


def run_watcher(watcher: EmailWatcher):
    """Watch /Approved indefinitely; send emails when approval files arrive."""
    # Handle files already there before the watcher starts
    watcher.process_existing()

    handler = ApprovedEmailHandler(watcher)
    observer = Observer()
    observer.schedule(handler, str(watcher.approved), recursive=False)
    observer.start()
    logger.info("Watching /Approved for email approvals. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    logger.info("Email watcher stopped.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Email Watcher — auto-sends approved email drafts via Gmail"
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
        help="Log intended actions without sending (safe testing mode)",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--watch",
        action="store_true",
        help="Watch /Approved folder and send approved emails automatically",
    )
    group.add_argument(
        "--send",
        metavar="FILENAME",
        help="Immediately send one specific approved file (must be in /Approved/)",
    )

    args = parser.parse_args()
    watcher = EmailWatcher(args.vault, dry_run=args.dry_run)

    if args.watch:
        run_watcher(watcher)
    elif args.send:
        approved_file = watcher.approved / args.send
        if not approved_file.exists():
            logger.error("File not found in /Approved: %s", args.send)
            sys.exit(1)
        success = watcher.send_approved_email(approved_file)
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
