"""
Gmail Sender — OAuth2 helper and email sending utilities.

Used by the MCP server to send emails via Gmail API.

Scopes: gmail.send only (minimal permissions, cannot read mail)

The token is saved separately from the watcher token so that the
read-only watcher credentials are not affected.

Token path: GMAIL_SEND_TOKEN_PATH env var (default: .gmail_send_token.json)
Credentials: GMAIL_CREDENTIALS_PATH env var (same credentials.json as watcher)
"""
import base64
import json
import os
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# ── Scope (send-only — cannot read mail) ─────────────────────────────────────
SEND_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

_ROOT = Path(__file__).parent.parent


def _load_env():
    """Load .env from project root into os.environ (idempotent)."""
    env_file = _ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()


def _credentials_path() -> Path:
    raw = os.getenv("GMAIL_CREDENTIALS_PATH", str(_ROOT / "gmail_credentials.json"))
    return Path(raw)


def _send_token_path() -> Path:
    raw = os.getenv("GMAIL_SEND_TOKEN_PATH", str(_ROOT / ".gmail_send_token.json"))
    return Path(raw)


def get_gmail_service():
    """
    Return an authenticated Gmail API service object (send-only scope).

    On first call this opens a browser for the OAuth2 consent flow.
    The resulting token is saved to GMAIL_SEND_TOKEN_PATH and reused
    (with automatic refresh) on subsequent calls.

    Raises:
        SystemExit: if the google-auth packages are not installed.
        FileNotFoundError: if gmail_credentials.json is missing.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print(
            "ERROR: Gmail packages not installed.\n"
            "Run:  uv sync --extra gmail\n"
            "  or: pip install google-auth google-auth-oauthlib google-api-python-client",
            file=sys.stderr,
        )
        raise SystemExit(1)

    creds_file = _credentials_path()
    if not creds_file.exists():
        raise FileNotFoundError(
            f"Gmail credentials not found: {creds_file}\n"
            "Download OAuth2 credentials from Google Cloud Console and save as\n"
            f"{creds_file}"
        )

    token_file = _send_token_path()
    creds = None

    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), SEND_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(creds_file), SEND_SCOPES
            )
            creds = flow.run_local_server(port=0)

        token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("gmail", "v1", credentials=creds)


def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    reply_to: str = "",
    from_name: str = "",
) -> dict:
    """
    Send a plain-text email via Gmail API.

    Args:
        to:         Recipient address (or comma-separated list).
        subject:    Email subject line.
        body:       Plain-text email body.
        cc:         Optional CC addresses (comma-separated).
        reply_to:   Optional Reply-To address.
        from_name:  Optional display name for the From field.

    Returns:
        dict with keys: message_id, thread_id, status
    """
    service = get_gmail_service()

    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc
    if reply_to:
        msg["Reply-To"] = reply_to

    from_email = os.getenv("GMAIL_FROM_EMAIL", "me")
    if from_name and from_email != "me":
        msg["From"] = f"{from_name} <{from_email}>"

    msg.attach(MIMEText(body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()

    return {
        "message_id": result.get("id"),
        "thread_id": result.get("threadId"),
        "status": "sent",
    }


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test Gmail send")
    parser.add_argument("--to", required=True, help="Recipient email")
    parser.add_argument("--subject", default="Test from AI Employee MCP", help="Subject")
    parser.add_argument("--body", default="This is a test email from the AI Employee MCP server.", help="Body")
    args = parser.parse_args()

    print(f"Sending to: {args.to}")
    result = send_email(to=args.to, subject=args.subject, body=args.body)
    print(f"Sent! Message ID: {result['message_id']}")
