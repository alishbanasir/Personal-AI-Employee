"""
AI Employee MCP Server — exposes vault operations as tools for Claude Code.

Provides Claude with structured tools to:
  - Inspect vault folder contents and stats
  - Create LinkedIn post approval drafts
  - Move files through the HITL workflow
  - Execute approved LinkedIn posts via Playwright
  - Append to vault action logs

The server runs over stdio and is launched automatically by Claude Code
via the .mcp.json config in the project root.

Usage (normally launched by Claude Code, not directly):
    python src/mcp_server.py
"""
import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Resolve vault path from environment (set in .mcp.json)
# ---------------------------------------------------------------------------

# Load .env from project root so VAULT_PATH can live there
_ROOT = Path(__file__).parent.parent
_ENV_FILE = _ROOT / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

VAULT = Path(
    os.getenv("VAULT_PATH", str(_ROOT / "AI_Employee_Vault"))
).resolve()

logging.basicConfig(level=logging.WARNING)  # keep MCP stdio clean

# ---------------------------------------------------------------------------
# MCP server setup (requires: pip install mcp)
# ---------------------------------------------------------------------------

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    print(
        "ERROR: 'mcp' package not found.\n"
        "Install it with:  uv add mcp  or  pip install mcp",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

mcp = FastMCP(
    "ai-employee",
    instructions="""
AI Employee Vault tools.  Use these in the following order:

1. get_vault_stats          — see what is where
2. list_vault_folder        — inspect a specific folder
3. read_vault_file          — read a specific file
4. draft_linkedin_post      — save a LinkedIn draft to /Pending_Approval (requires human approval)
5. draft_email              — save an email draft to /Pending_Approval (requires human approval)
6. move_vault_file          — advance a file through the workflow
7. execute_approved_post    — publish an approved LinkedIn post via Playwright
8. send_approved_email      — send an approved email via Gmail API
9. log_vault_action         — record any manual decision in today's log

IMPORTANT: Never call execute_approved_post or send_approved_email unless the file is
already in /Approved/.  Always use draft_email for new outbound emails — never send
directly.
""",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> dict:
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


def _append_log(action_type: str, details: dict):
    logs_dir = VAULT / "Logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
    entry = {
        "timestamp": datetime.now().isoformat(),
        "actor": "mcp_server",
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


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def get_vault_stats() -> str:
    """
    Return a JSON object with file counts for every vault folder.
    Use this first to get an overview of current system state.
    """
    folders = [
        "Inbox", "Needs_Action", "Plans", "Done",
        "Pending_Approval", "Approved", "Rejected",
        "Briefings", "Logs", "Accounting",
    ]
    stats: dict = {}
    for name in folders:
        path = VAULT / name
        if path.exists():
            stats[name] = len([
                f for f in path.glob("*")
                if f.is_file() and f.name not in {".gitkeep", ".DS_Store"}
            ])
        else:
            stats[name] = 0
    return json.dumps({"vault": str(VAULT), "counts": stats}, indent=2)


@mcp.tool()
def list_vault_folder(folder: str) -> str:
    """
    List all .md files in a vault folder.

    Args:
        folder: Folder name — one of: Inbox, Needs_Action, Plans, Done,
                Pending_Approval, Approved, Rejected, Briefings, Logs, Accounting
    """
    folder_path = VAULT / folder
    if not folder_path.exists():
        return f"Folder not found: {folder}"
    files = sorted(
        f.name for f in folder_path.glob("*.md") if f.name != ".gitkeep"
    )
    if not files:
        return f"/{folder}/ is empty."
    return f"Files in /{folder}/:\n" + "\n".join(f"  - {f}" for f in files)


@mcp.tool()
def read_vault_file(folder: str, filename: str) -> str:
    """
    Read a file from a vault folder and return its contents.

    Args:
        folder:   Vault folder name (e.g. "Needs_Action")
        filename: File name including extension (e.g. "SOCIAL_20260223_task.md")
    """
    file_path = VAULT / folder / filename
    if not file_path.exists():
        return f"File not found: {folder}/{filename}"
    return file_path.read_text(encoding="utf-8")


@mcp.tool()
def draft_linkedin_post(post_content: str, source_task_file: str) -> str:
    """
    Save a drafted LinkedIn post to /Pending_Approval for human review.

    The human must move the file to /Approved/ to publish it.
    The post will NOT be sent until that approval step is completed.

    Args:
        post_content:     Full text of the LinkedIn post (max 3000 chars recommended).
        source_task_file: Filename in /Needs_Action that triggered this draft.

    Returns:
        Path of the created approval file.
    """
    import re

    ts = datetime.now()
    ts_str = ts.strftime("%Y%m%d_%H%M%S")
    expires = ts + timedelta(hours=24)
    safe_stem = re.sub(r"[^\w]", "_", Path(source_task_file).stem)[:30]
    filename = f"SOCIAL_{ts_str}_linkedin_{safe_stem}.md"
    approval_path = VAULT / "Pending_Approval" / filename
    char_count = len(post_content)

    (VAULT / "Pending_Approval").mkdir(parents=True, exist_ok=True)

    content = f"""---
type: social_post_approval
platform: linkedin
action: linkedin_post
created: {ts.isoformat()}
expires: {expires.isoformat()}
status: pending
source_task: {source_task_file}
character_count: {char_count}
---

## Proposed LinkedIn Post

{post_content}

---

## Post Details

- **Platform:** LinkedIn
- **Characters:** {char_count} / 3000
- **Created:** {ts.strftime('%Y-%m-%d %H:%M')}
- **Expires:** {expires.strftime('%Y-%m-%d %H:%M')} (24-hour approval window)

## Instructions

- To **approve and publish**: Move this file to `/Approved/`
- To **reject**: Move this file to `/Rejected/`

> The post will be published automatically once moved to `/Approved/`.
"""

    approval_path.write_text(content, encoding="utf-8")
    _append_log("draft_linkedin_post", {
        "file": filename,
        "char_count": char_count,
        "source": source_task_file,
    })
    return (
        f"Draft saved: Pending_Approval/{filename}\n"
        f"Characters: {char_count}/3000\n"
        f"Next step: Review the draft and move it to /Approved/ to publish."
    )


@mcp.tool()
def move_vault_file(filename: str, from_folder: str, to_folder: str) -> str:
    """
    Move a file between vault folders to advance it through the workflow.

    Common transitions:
      Needs_Action  → Plans            (plan created)
      Needs_Action  → Pending_Approval (action needs review)
      Pending_Approval → Approved      (human approved)
      Pending_Approval → Rejected      (human rejected)
      Approved      → Done             (action executed)

    Args:
        filename:    File name including extension.
        from_folder: Source folder (e.g. "Needs_Action").
        to_folder:   Destination folder (e.g. "Done").
    """
    src = VAULT / from_folder / filename
    dst_dir = VAULT / to_folder
    dst = dst_dir / filename

    if not src.exists():
        return f"File not found: {from_folder}/{filename}"

    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    _append_log("file_moved", {
        "file": filename,
        "from": from_folder,
        "to": to_folder,
    })
    return f"Moved: {from_folder}/{filename} → {to_folder}/{filename}"


@mcp.tool()
def execute_approved_post(filename: str) -> str:
    """
    Execute an approved LinkedIn post via Playwright.

    The file MUST already be in /Approved/ and must have type: social_post_approval
    in its frontmatter. After a successful post it is moved to /Done/.

    Args:
        filename: The approved file name (e.g. "SOCIAL_20260223_linkedin_task.md")
    """
    approved_path = VAULT / "Approved" / filename
    if not approved_path.exists():
        return f"File not found in /Approved: {filename}"

    # Delegate to social_media_manager.py to keep Playwright isolated
    script = Path(__file__).parent / "social_media_manager.py"
    result = subprocess.run(
        [sys.executable, str(script), "--vault", str(VAULT), "--post", filename],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode == 0:
        _append_log("linkedin_post_executed", {"file": filename, "status": "success"})
        return f"Post published successfully: {filename}\n{result.stdout.strip()}"
    else:
        _append_log("linkedin_post_failed", {
            "file": filename,
            "status": "failed",
            "stderr": result.stderr.strip(),
        })
        return (
            f"Post execution failed for: {filename}\n"
            f"Error: {result.stderr.strip()}"
        )


@mcp.tool()
def draft_email(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    reply_to: str = "",
) -> str:
    """
    Save a drafted email to /Pending_Approval for human review.

    The email will NOT be sent until a human moves the file to /Approved/.
    Use this for ALL outbound emails — never send directly.

    Args:
        to:       Recipient address (or comma-separated list).
        subject:  Email subject line.
        body:     Plain-text email body.
        cc:       Optional CC addresses (comma-separated).
        reply_to: Optional Reply-To address.

    Returns:
        Path of the created approval file and next steps.
    """
    import re

    ts = datetime.now()
    ts_str = ts.strftime("%Y%m%d_%H%M%S")
    expires = ts + timedelta(hours=24)
    safe_subject = re.sub(r"[^\w]", "_", subject)[:30]
    filename = f"EMAIL_{ts_str}_{safe_subject}.md"
    approval_path = VAULT / "Pending_Approval" / filename

    (VAULT / "Pending_Approval").mkdir(parents=True, exist_ok=True)

    content = f"""---
type: email_approval
action: send_email
created: {ts.isoformat()}
expires: {expires.isoformat()}
status: pending
to: {to}
cc: {cc}
reply_to: {reply_to}
subject: {subject}
---

## Proposed Email

**To:** {to}
{f"**CC:** {cc}" if cc else ""}
{f"**Reply-To:** {reply_to}" if reply_to else ""}
**Subject:** {subject}

---

{body}

---

## Instructions

- To **approve and send**: Move this file to `/Approved/`
- To **reject**: Move this file to `/Rejected/`
- To **edit**: Modify the body above, then move to `/Approved/`

> The email will be sent automatically once moved to `/Approved/`.
> Approval window: 24 hours (expires {expires.strftime('%Y-%m-%d %H:%M')})
"""

    approval_path.write_text(content, encoding="utf-8")
    _append_log("draft_email", {
        "file": filename,
        "to": to,
        "subject": subject,
        "cc": cc,
    })
    return (
        f"Email draft saved: Pending_Approval/{filename}\n"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"Next step: Review the draft and move it to /Approved/ to send."
    )


@mcp.tool()
def send_approved_email(filename: str) -> str:
    """
    Send an approved email via Gmail API.

    The file MUST already be in /Approved/ and must have type: email_approval
    in its frontmatter.  After a successful send it is moved to /Done/.

    Requires: uv sync --extra gmail  and  python src/gmail_auth.py (one-time setup).

    Args:
        filename: The approved file name (e.g. "EMAIL_20260226_Re_your_question.md")
    """
    approved_path = VAULT / "Approved" / filename
    if not approved_path.exists():
        return f"File not found in /Approved/: {filename}"

    content = approved_path.read_text(encoding="utf-8")
    meta = _parse_frontmatter(content)

    if meta.get("type") != "email_approval":
        return f"File is not an email approval (type={meta.get('type')}): {filename}"

    to = meta.get("to", "")
    subject = meta.get("subject", "")
    cc = meta.get("cc", "")
    reply_to = meta.get("reply_to", "")

    if not to or not subject:
        return "Cannot send: missing 'to' or 'subject' in frontmatter."

    # Extract body: everything between the second --- block and the final ---
    parts = content.split("---")
    # parts[0] = '', parts[1] = frontmatter, parts[2] = rest of doc
    body_section = "---".join(parts[2:]) if len(parts) > 2 else ""
    # Strip the instruction footer (starts with "## Instructions")
    if "## Instructions" in body_section:
        body_section = body_section[: body_section.index("## Instructions")]
    # Clean up the header lines (To/Subject/etc.) — keep only lines after the separator
    lines = body_section.splitlines()
    body_lines: list[str] = []
    past_header = False
    for line in lines:
        if line.strip() == "---" and not past_header:
            past_header = True
            continue
        if past_header:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()

    # Dry-run guard
    if os.getenv("DRY_RUN", "false").lower() == "true":
        _append_log("email_dry_run", {"file": filename, "to": to, "subject": subject})
        return (
            f"DRY RUN — email NOT sent.\n"
            f"Would send to: {to}\n"
            f"Subject: {subject}\n"
            f"Body preview: {body[:100]}..."
        )

    try:
        # Import here so the server still starts if gmail packages are absent
        sys.path.insert(0, str(Path(__file__).parent))
        from gmail_sender import send_email  # type: ignore

        result = send_email(
            to=to,
            subject=subject,
            body=body,
            cc=cc,
            reply_to=reply_to,
        )

        # Move file to Done
        done_dir = VAULT / "Done"
        done_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(approved_path), str(done_dir / filename))

        _append_log("email_sent", {
            "file": filename,
            "to": to,
            "subject": subject,
            "message_id": result.get("message_id"),
        })
        return (
            f"Email sent successfully!\n"
            f"To: {to}\n"
            f"Subject: {subject}\n"
            f"Gmail Message ID: {result.get('message_id')}\n"
            f"File moved to: Done/{filename}"
        )

    except ImportError:
        return (
            "ERROR: Gmail packages not installed.\n"
            "Run: uv sync --extra gmail\n"
            "Then run: python src/gmail_auth.py"
        )
    except FileNotFoundError as exc:
        return f"ERROR: {exc}"
    except Exception as exc:  # noqa: BLE001
        _append_log("email_failed", {
            "file": filename,
            "to": to,
            "error": str(exc),
        })
        return f"ERROR sending email: {exc}"


@mcp.tool()
def log_vault_action(action_type: str, details_json: str) -> str:
    """
    Append an entry to today's vault JSON log.

    Args:
        action_type:  Short identifier (e.g. "task_reviewed", "decision_made").
        details_json: JSON string with any additional key-value pairs.
    """
    try:
        details = json.loads(details_json)
    except json.JSONDecodeError:
        details = {"note": details_json}
    _append_log(action_type, details)
    return f"Logged action: {action_type}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
