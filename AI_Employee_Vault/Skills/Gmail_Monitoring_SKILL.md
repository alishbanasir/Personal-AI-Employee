---
name: gmail-monitoring
version: 1.0
created: 2026-02-26
scripts:
  - src/gmail_watcher.py
launchers:
  - start_gmail_watcher.bat
auth_tokens:
  - .gmail_token.json
  - gmail_credentials.json
poll_interval: 60s
gmail_scope: readonly
---

# Skill: Gmail Monitoring

Polls the Gmail inbox every 60 seconds, identifies important emails, and converts them
into action files in `/Needs_Action/` for Claude to process.

This skill is **read-only** — it never replies, sends, or modifies emails.

---

## Workflow Overview

```
Gmail Inbox (unread)
        │
        │  gmail_watcher.py polls every 60s
        │  Filters by: IMPORTANT label, STARRED, priority senders, subject keywords
        ▼
New important email found
        │
        ▼
/Needs_Action/Email_<sender>_<subject>.md    ←── created automatically
        │
        │  Claude reads + reasons about it (/process-inbox)
        ▼
Draft reply / action  →  /Pending_Approval/  →  human approves  →  /Done/
```

---

## Starting the Watcher

### Double-click (recommended)
```bat
start_gmail_watcher.bat
```

### Command line
```bash
.venv\Scripts\python.exe src/gmail_watcher.py --vault AI_Employee_Vault
```

### With options
```bash
# Custom poll interval (120 seconds)
.venv\Scripts\python.exe src/gmail_watcher.py --vault AI_Employee_Vault --interval 120

# Dry run — logs detected emails without writing files
.venv\Scripts\python.exe src/gmail_watcher.py --vault AI_Employee_Vault --dry-run
```

Press `Ctrl+C` to stop.

---

## What Gets Monitored

The watcher polls Gmail for **unread inbox messages** and applies these filters in order:

### Filter 1 — Gmail Labels (highest priority)
| Label | Triggers action? |
|-------|-----------------|
| `IMPORTANT` (Google auto-label) | Yes |
| `STARRED` | Yes |

### Filter 2 — Priority Senders
Set in `.env`:
```env
GMAIL_PRIORITY_SENDERS=client@example.com,boss@company.com
```
Any unread email from these addresses creates an action file.

### Filter 3 — Subject Keywords
Set in `.env`:
```env
GMAIL_PRIORITY_KEYWORDS=invoice,urgent,payment,contract,ASAP
```
Any unread email whose subject contains these words creates an action file.

### Fallback — No Filters Configured
If **none** of the above env vars are set, the watcher captures **all unread inbox email**.
Configure `GMAIL_PRIORITY_SENDERS` or `GMAIL_PRIORITY_KEYWORDS` to narrow the scope.

---

## Action File Format

Each detected email creates a file in `/Needs_Action/`:

```
Email_<SenderName>_<Subject>.md
```

File contents:
```markdown
---
type: email
source: gmail
message_id: <Gmail message ID>
thread_id: <Gmail thread ID>
subject: "Email subject here"
sender: "Name <email@example.com>"
received: <RFC 2822 date>
priority: high | medium
importance_reason: Gmail label: IMPORTANT | Priority sender: x | Subject keyword: 'invoice'
status: pending
---

## Email Received
**From:** ...
**Subject:** ...
**Date:** ...
**Flagged because:** ...

---

## Body
<First 2000 chars of email body>

---

## Suggested Actions
- [ ] Review email content
- [ ] Determine required response or action
- [ ] Draft reply if needed (create task in Pending_Approval)
- [ ] Archive or file when complete
```

---

## Deduplication

The watcher tracks processed Gmail message IDs in:
```
/Logs/.gmail_seen_ids.json
```
This prevents the same email from creating multiple action files across restarts.

To reset (force re-processing all unread emails):
```bash
del AI_Employee_Vault\Logs\.gmail_seen_ids.json
```

---

## First-Time Setup

### 1. Get Gmail OAuth2 credentials
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable Gmail API
3. Create OAuth2 Desktop credentials
4. Download as `gmail_credentials.json` → place in project root

### 2. Authenticate (one-time)
```bash
.venv\Scripts\python.exe src/gmail_watcher.py --vault AI_Employee_Vault
```
A browser window opens → sign in with Google → grant Gmail read access.
Token saved to `.gmail_token.json` — auto-refreshes on subsequent runs.

### 3. Install dependencies
```bash
uv sync --extra gmail
# or: pip install google-auth google-auth-oauthlib google-api-python-client
```

---

## Environment Variables (`.env`)

```env
GMAIL_CREDENTIALS_PATH=gmail_credentials.json
GMAIL_TOKEN_PATH=.gmail_token.json
GMAIL_POLL_INTERVAL=60                          # seconds between polls
GMAIL_PRIORITY_SENDERS=client@example.com       # comma-separated
GMAIL_PRIORITY_KEYWORDS=invoice,urgent,payment  # comma-separated
DRY_RUN=false
```

---

## Priority Classification

| Condition | Priority assigned |
|-----------|-----------------|
| Gmail `IMPORTANT` label | `high` |
| Gmail `STARRED` label | `medium` |
| Priority sender match | `medium` |
| Subject keyword match | `medium` |
| All unread (no filters) | `medium` |

Per `Company_Handbook.md`, items in `/Needs_Action/` older than **24 hours** are automatically escalated to `high` priority.

---

## Integration with Process Inbox

After the watcher creates action files, run `/process-inbox` in Claude Code:
- Claude reads each file
- Classifies the email (newsletter, client message, security alert, etc.)
- Creates a Plan in `/Plans/`
- Routes to `/Pending_Approval/` if a reply is needed, or `/Done/` if it's informational

---

## Running Alongside Other Watchers

All three watchers can run simultaneously in separate terminal windows:

| Watcher | Launcher | Monitors |
|---------|----------|---------|
| Gmail inbox | `start_gmail_watcher.bat` | Gmail → `/Needs_Action/` |
| Email sender | `start_email_watcher.bat` | `/Approved/` email drafts → Gmail send |
| LinkedIn poster | `start_linkedin_watcher.bat` | `/Approved/` social drafts → LinkedIn |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Gmail dependencies missing" | Run `uv sync --extra gmail` |
| "Credentials file not found" | Download `gmail_credentials.json` from Google Cloud Console |
| Token expired | Delete `.gmail_token.json` and re-run to re-authenticate |
| Emails not appearing in /Needs_Action | Check filters — may be too restrictive; verify labels in Gmail |
| Duplicate action files | Check `/Logs/.gmail_seen_ids.json` exists; watcher may have crashed before saving state |
| Body shows as HTML tags | Email was HTML-only; watcher strips tags but layout may look odd |
