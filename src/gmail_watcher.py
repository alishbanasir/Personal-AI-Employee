"""
Gmail Watcher — monitors Gmail inbox for important emails.

Polls the Gmail API every N seconds and converts new important emails
into .md action files in AI_Employee_Vault/Needs_Action/.

Filtering logic (any match triggers an action file):
  - Gmail label IMPORTANT (Google's auto-classification)
  - Gmail label STARRED
  - Unread emails from senders in PRIORITY_SENDERS env var
  - Subject keywords in PRIORITY_KEYWORDS env var

Usage:
    python src/gmail_watcher.py --vault /path/to/AI_Employee_Vault
    python src/gmail_watcher.py --vault /path/to/AI_Employee_Vault --dry-run
    python src/gmail_watcher.py --vault /path/to/AI_Employee_Vault --interval 120

Prerequisites:
    1. Download OAuth2 credentials from Google Cloud Console and save as
       gmail_credentials.json in the project root (next to pyproject.toml).
    2. Run once interactively to complete the OAuth flow — a token file is
       saved at GMAIL_TOKEN_PATH so subsequent runs are non-interactive.
    3. uv sync --extra gmail   (or pip install google-auth google-auth-oauthlib
                                    google-api-python-client)
"""
import argparse
import base64
import email as email_lib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [GmailWatcher] %(levelname)s: %(message)s",
)
logger = logging.getLogger("GmailWatcher")

# ── Constants ────────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Gmail query run on every poll — only unread inbox messages
BASE_QUERY = "in:inbox is:unread"

# Labels that automatically qualify an email as important
IMPORTANT_LABELS = {"IMPORTANT", "STARRED"}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_env_list(var: str) -> list[str]:
    """Return comma-separated env var as a cleaned list, or []."""
    raw = os.getenv(var, "")
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _build_service(credentials_path: Path, token_path: Path):
    """Authenticate and return a Gmail API service object."""
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        logger.error(
            "Gmail dependencies missing. Run: uv sync --extra gmail\n"
            "  or: pip install google-auth google-auth-oauthlib google-api-python-client"
        )
        sys.exit(1)

    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing expired Gmail token...")
            creds.refresh(Request())
        else:
            if not credentials_path.exists():
                logger.error(
                    f"Credentials file not found: {credentials_path}\n"
                    "  Download it from Google Cloud Console → APIs & Services → Credentials."
                )
                sys.exit(1)
            logger.info("Starting OAuth2 flow — a browser window will open...")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json(), encoding="utf-8")
        logger.info(f"Token saved: {token_path}")

    service = build("gmail", "v1", credentials=creds)
    logger.info("Gmail API authenticated successfully.")
    return service


def _decode_body(payload: dict) -> str:
    """Extract plain-text body from a Gmail message payload."""
    def _decode_part(part: dict) -> str:
        data = part.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        return _decode_part(payload)

    if mime_type == "text/html":
        # Fall back to HTML if no plain-text part available
        raw_html = _decode_part(payload)
        return re.sub(r"<[^>]+>", "", raw_html).strip()

    # Multipart — prefer text/plain
    parts = payload.get("parts", [])
    plain = ""
    html = ""
    for part in parts:
        mt = part.get("mimeType", "")
        if mt == "text/plain":
            plain = _decode_part(part)
        elif mt == "text/html":
            html = re.sub(r"<[^>]+>", "", _decode_part(part)).strip()
        elif mt.startswith("multipart/"):
            # Recurse one level for nested multipart
            nested = _decode_body(part)
            if nested:
                plain = nested
    return plain or html


def _extract_email_address(header_value: str) -> str:
    """Extract bare email address from a 'Name <email>' header."""
    match = re.search(r"<([^>]+)>", header_value)
    return match.group(1).lower() if match else header_value.lower().strip()


# ── Core watcher class ───────────────────────────────────────────────────────

class GmailWatcher:
    def __init__(
        self,
        vault_path: str,
        credentials_path: str,
        token_path: str,
        check_interval: int = 60,
        dry_run: bool = False,
    ):
        self.vault = Path(vault_path).resolve()
        self.needs_action = self.vault / "Needs_Action"
        self.logs_dir = self.vault / "Logs"
        self.check_interval = check_interval
        self.dry_run = dry_run or os.getenv("DRY_RUN", "false").lower() == "true"

        self.needs_action.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # State file — tracks message IDs already processed so we don't
        # create duplicate action files across restarts.
        self.state_file = self.vault / "Logs" / ".gmail_seen_ids.json"
        self.seen_ids: set[str] = self._load_seen_ids()

        # Filtering config from environment
        self.priority_senders: list[str] = _load_env_list("GMAIL_PRIORITY_SENDERS")
        self.priority_keywords: list[str] = _load_env_list("GMAIL_PRIORITY_KEYWORDS")

        logger.info(f"Vault: {self.vault}")
        logger.info(f"Priority senders: {self.priority_senders or '(none configured)'}")
        logger.info(f"Priority keywords: {self.priority_keywords or '(none configured)'}")
        logger.info(f"Dry run: {self.dry_run}")

        self.service = _build_service(Path(credentials_path), Path(token_path))

    # ── State persistence ────────────────────────────────────────────────────

    def _load_seen_ids(self) -> set[str]:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                ids = set(data.get("seen_ids", []))
                logger.info(f"Loaded {len(ids)} previously-seen message IDs.")
                return ids
            except (json.JSONDecodeError, KeyError):
                pass
        return set()

    def _save_seen_ids(self):
        self.state_file.write_text(
            json.dumps({"seen_ids": list(self.seen_ids)}, indent=2),
            encoding="utf-8",
        )

    # ── Filtering logic ──────────────────────────────────────────────────────

    def _is_important(self, msg_meta: dict, subject: str, sender_email: str) -> tuple[bool, str]:
        """
        Returns (is_important, reason_string).
        Checks in priority order:
          1. Gmail IMPORTANT / STARRED label
          2. Sender in GMAIL_PRIORITY_SENDERS
          3. Subject contains a keyword from GMAIL_PRIORITY_KEYWORDS
        If none configured AND no labels match, accepts all unread inbox mail.
        """
        label_ids = set(msg_meta.get("labelIds", []))

        # Label-based
        matched_labels = label_ids & IMPORTANT_LABELS
        if matched_labels:
            return True, f"Gmail label: {', '.join(matched_labels)}"

        # Sender-based
        if self.priority_senders and sender_email in self.priority_senders:
            return True, f"Priority sender: {sender_email}"

        # Keyword-based
        if self.priority_keywords:
            subject_lower = subject.lower()
            for kw in self.priority_keywords:
                if kw in subject_lower:
                    return True, f"Subject keyword: '{kw}'"
            # Keywords are configured but none matched — skip
            return False, ""

        # No filters configured at all → accept everything unread
        if not self.priority_senders and not self.priority_keywords:
            return True, "all unread (no filters configured)"

        return False, ""

    # ── Main poll loop ───────────────────────────────────────────────────────

    def check_for_updates(self) -> list[dict]:
        """Poll Gmail and return list of new important messages."""
        results = (
            self.service.users()
            .messages()
            .list(userId="me", q=BASE_QUERY, maxResults=50)
            .execute()
        )
        messages = results.get("messages", [])
        new_items = []

        for msg_stub in messages:
            msg_id = msg_stub["id"]
            if msg_id in self.seen_ids:
                continue

            # Fetch full metadata + body
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )

            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            subject = headers.get("subject", "(no subject)")
            sender = headers.get("from", "(unknown sender)")
            date_str = headers.get("date", "")
            sender_email = _extract_email_address(sender)

            important, reason = self._is_important(msg, subject, sender_email)
            if not important:
                # Still mark as seen so we don't re-evaluate it every cycle
                self.seen_ids.add(msg_id)
                continue

            body = _decode_body(msg.get("payload", {}))

            new_items.append(
                {
                    "id": msg_id,
                    "subject": subject,
                    "sender": sender,
                    "sender_email": sender_email,
                    "date": date_str,
                    "reason": reason,
                    "body": body,
                    "label_ids": msg.get("labelIds", []),
                    "thread_id": msg.get("threadId", ""),
                }
            )
            self.seen_ids.add(msg_id)

        return new_items

    # ── Action file creation ─────────────────────────────────────────────────

    def create_action_file(self, email: dict) -> Path:
        """Write a .md action file in Needs_Action for a single email."""
        now = datetime.now()

        # Extract sender display name (before the angle bracket, or use email address)
        sender_raw = email["sender"].split("<")[0].strip().strip('"') or email["sender_email"]
        safe_sender = re.sub(r"[^\w\-]", "_", sender_raw)[:30].strip("_")
        safe_subject = re.sub(r"[^\w\-]", "_", email["subject"])[:50].strip("_")
        filename = f"Email_{safe_sender}_{safe_subject}.md"
        dest = self.needs_action / filename

        # Truncate very long bodies to keep files manageable
        body_preview = email["body"].strip()
        if len(body_preview) > 2000:
            body_preview = body_preview[:2000] + "\n\n_[body truncated — full email in Gmail]_"

        priority = "high" if "IMPORTANT" in email["label_ids"] else "medium"

        content = f"""---
type: email
source: gmail
message_id: {email['id']}
thread_id: {email['thread_id']}
subject: "{email['subject'].replace('"', "'")}"
sender: "{email['sender'].replace('"', "'")}"
received: {email['date']}
priority: {priority}
importance_reason: {email['reason']}
status: pending
---

## Email Received

**From:** {email['sender']}
**Subject:** {email['subject']}
**Date:** {email['date']}
**Flagged because:** {email['reason']}

---

## Body

{body_preview}

---

## Suggested Actions
- [ ] Review email content
- [ ] Determine required response or action
- [ ] Draft reply if needed (create task in Pending_Approval)
- [ ] Archive or file when complete

## Notes
_Claude: Add your analysis and action plan here._
"""

        if self.dry_run:
            logger.info(f"[DRY RUN] Would create: {filename}")
        else:
            dest.write_text(content, encoding="utf-8")
            self._log_action(email, filename, now)
            self._update_dashboard(email, filename, now)

        return dest

    # ── Logging & dashboard ──────────────────────────────────────────────────

    def _log_action(self, email: dict, action_file: str, now: datetime):
        log_file = self.logs_dir / f"{now.strftime('%Y-%m-%d')}.json"
        entry = {
            "timestamp": now.isoformat(),
            "action_type": "email_received",
            "actor": "gmail_watcher",
            "source": email["sender"],
            "subject": email["subject"],
            "message_id": email["id"],
            "reason": email["reason"],
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

    def _update_dashboard(self, email: dict, action_file: str, now: datetime):
        dashboard = self.vault / "Dashboard.md"
        if not dashboard.exists():
            return
        text = dashboard.read_text(encoding="utf-8")
        new_row = (
            f"| {now.strftime('%Y-%m-%d %H:%M')} | "
            f"Email from `{email['sender_email']}`: _{email['subject'][:40]}_ → `{action_file}` | ⏳ Pending |"
        )
        marker = "| — | System initialized | ✅ |"
        if marker in text:
            text = text.replace(marker, f"{new_row}\n{marker}")
        else:
            text += f"\n{new_row}\n"
        dashboard.write_text(text, encoding="utf-8")

    # ── Main run loop ────────────────────────────────────────────────────────

    def run(self):
        logger.info(f"Gmail Watcher started (poll interval: {self.check_interval}s)")
        logger.info("Press Ctrl+C to stop.")
        while True:
            try:
                items = self.check_for_updates()
                if items:
                    logger.info(f"Found {len(items)} new important email(s).")
                    for item in items:
                        path = self.create_action_file(item)
                        logger.info(f"  → {path.name}")
                    if not self.dry_run:
                        self._save_seen_ids()
                else:
                    logger.debug("No new important emails.")
            except Exception as e:
                logger.error(f"Poll error: {e}", exc_info=True)
            time.sleep(self.check_interval)


# ── CLI entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="AI Employee Gmail Watcher — monitors inbox for important emails"
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("VAULT_PATH", "AI_Employee_Vault"),
        help="Absolute path to AI_Employee_Vault directory",
    )
    parser.add_argument(
        "--credentials",
        default=os.getenv("GMAIL_CREDENTIALS_PATH", "gmail_credentials.json"),
        help="Path to Gmail OAuth2 client secrets JSON (from Google Cloud Console)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv(
            "GMAIL_TOKEN_PATH",
            str(Path(__file__).parent.parent / ".gmail_token.json"),
        ),
        help="Path where the OAuth2 token will be saved after first login",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("GMAIL_POLL_INTERVAL", "60")),
        help="Poll interval in seconds (default: 60)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Log intended actions without writing files (safe testing mode)",
    )
    args = parser.parse_args()

    watcher = GmailWatcher(
        vault_path=args.vault,
        credentials_path=args.credentials,
        token_path=args.token,
        check_interval=args.interval,
        dry_run=args.dry_run,
    )
    watcher.run()


if __name__ == "__main__":
    main()
