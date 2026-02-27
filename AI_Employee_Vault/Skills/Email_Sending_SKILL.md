---
name: email-sending
version: 1.0
created: 2026-02-26
scripts:
  - src/email_watcher.py
  - src/gmail_sender.py
  - src/gmail_auth.py
launchers:
  - start_email_watcher.bat
mcp_tools:
  - draft_email
  - send_approved_email
  - move_vault_file
auth_tokens:
  - .gmail_send_token.json
  - gmail_credentials.json
---

# Skill: Email Sending

Drafts, approves, and sends emails via the Gmail API using a Human-in-the-Loop (HITL) workflow.
Claude writes the draft — you approve — automation sends it.

**The email is NEVER sent without a human moving the file to `/Approved/`.**

---

## Workflow Overview

```
User request / Needs_Action email task
        │
        ▼
[Claude] draft_email() MCP tool
        │
        ▼
/Pending_Approval/EMAIL_YYYYMMDD_HHmmss_<subject>.md
        │
        │  Human reviews draft
        │  Moves file to /Approved/
        ▼
/Approved/EMAIL_YYYYMMDD_HHmmss_<subject>.md
        │
        │  start_email_watcher.bat (watchdog)
        │  OR send_approved_email() MCP tool
        ▼
Email sent via Gmail API  →  file moved to /Done/
```

---

## Step 1 — Draft the Email

### Option A: Ask Claude
Tell Claude what email to send. Claude will draft it and save to `/Pending_Approval/`.

Example:
> "Draft an email to client@example.com thanking them for their payment of $500 for the invoice."

### Option B: MCP tool directly
```
draft_email(
    to      = "client@example.com",
    subject = "Invoice Paid — Thank You",
    body    = "Hi,\n\nThank you for your payment...",
    cc      = "",          # optional
    reply_to = ""          # optional
)
```

### Option C: Process a Needs_Action item
When a `/Needs_Action/` item requires an email reply, Claude uses `draft_email` as part of the `/process-inbox` workflow.

---

## Step 2 — Review the Draft

The draft file is saved to:
```
/Pending_Approval/EMAIL_YYYYMMDD_HHmmss_<subject>.md
```

Open it in Obsidian or any text editor. The file contains:
- To / CC / Reply-To fields
- Full email body
- 24-hour expiry window
- Approval and rejection instructions

**To edit:** Modify the body directly in the file, then move to `/Approved/`.
**To approve:** Move the file to `/Approved/`.
**To reject:** Move the file to `/Rejected/`.

---

## Step 3 — Send the Approved Email

### Auto (recommended) — run the watcher
```bat
start_email_watcher.bat
```
Double-click the batch file. It watches `/Approved/` continuously and sends the email the moment you move a file there. The watcher also scans existing `/Approved/` files at startup (catches emails approved while it was off).

### Manual — one-shot send
```bash
.venv\Scripts\python.exe src/email_watcher.py --vault AI_Employee_Vault --send EMAIL_YYYYMMDD_HHmmss_Subject.md
```

### Via MCP tool
```
send_approved_email(filename="EMAIL_YYYYMMDD_HHmmss_Subject.md")
```

---

## Email Rules (Company Handbook)

| Rule | Detail |
|------|--------|
| Known contacts | Auto-draft allowed; human approval required to send |
| New contacts | Always require human approval — no exceptions |
| Tone | Professional, concise. No emojis unless sender used them first |
| Rate limit | Max 10 emails per hour |
| Bulk email | Never — always requires explicit human approval |
| Sensitive content | Payments, contracts, legal — always require approval |

---

## Gmail API Authentication

Sending uses a **separate token** from reading (read-only watcher vs. send-only sender).

| Token file | Scope | Used by |
|-----------|-------|---------|
| `.gmail_token.json` | `gmail.readonly` | `gmail_watcher.py` (reading inbox) |
| `.gmail_send_token.json` | `gmail.send` | `gmail_sender.py` + `email_watcher.py` |

### First-time setup (one-time)
```bash
.venv\Scripts\python.exe src/gmail_auth.py
```
A browser window opens → log in with Google → token saved to `.gmail_send_token.json`.

The token auto-refreshes using the stored `refresh_token` — you won't need to re-authenticate.

---

## Dry Run (Safe Testing)

```bash
.venv\Scripts\python.exe src/email_watcher.py --vault AI_Employee_Vault --watch --dry-run
```
Logs what *would* happen (recipient, subject, body preview) without sending anything.

---

## Environment Variables (`.env`)

```env
GMAIL_CREDENTIALS_PATH=gmail_credentials.json
GMAIL_SEND_TOKEN_PATH=.gmail_send_token.json
GMAIL_FROM_EMAIL=your@gmail.com   # optional: sets From display address
DRY_RUN=false
```

---

## File Naming Convention

| Stage | Pattern |
|-------|---------|
| Pending | `EMAIL_YYYYMMDD_HHmmss_<subject_safe>.md` |
| Approved | same filename, moved to `/Approved/` |
| Done | same filename, moved to `/Done/` |

---

## Approval File Frontmatter Reference

```yaml
type: email_approval         # must be this value for the watcher to process it
action: send_email
to: recipient@example.com
subject: Email Subject
cc:                          # optional
reply_to:                    # optional
expires: <ISO timestamp>     # 24h window
status: pending
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Gmail packages not installed" | Run `uv sync --extra gmail` |
| "File not found in /Approved" | Check filename spelling exactly |
| Token expired / auth error | Run `python src/gmail_auth.py` to re-authenticate |
| Email sent but watcher shows error | Check `/Logs/YYYY-MM-DD.json` for full error |
| Body extracted incorrectly | Check draft file — body must be between the two `---` separators |
| Rate limit hit | Wait — Gmail allows max 10 emails/hour per Company Handbook |
