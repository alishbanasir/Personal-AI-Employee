# Personal AI Employee — Silver Tier

**Hackathon 0: Building Autonomous FTEs in 2026**
**Tier:** Silver (Automation)

A local-first, agent-driven Personal AI Employee powered by Claude Code, an Obsidian vault, and an MCP server for real-world action execution.

---

## Architecture

```
External Sources (Files, Email)
      │
      ▼
┌─────────────────────────────────────────┐
│  PERCEPTION LAYER                       │
│  filesystem_watcher.py — /Inbox drops  │
│  gmail_watcher.py      — Gmail inbox   │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  OBSIDIAN VAULT (Local)                 │
│  /Inbox  /Needs_Action  /Plans  /Done   │
│  /Pending_Approval  /Approved           │
│  /Rejected  /Briefings  /Logs           │
│  Dashboard.md  Company_Handbook.md      │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  REASONING — Claude Code + Agent Skills │
│  /process-inbox      → Plan.md + route  │
│  /update-dashboard   → live stats       │
│  /daily-briefing     → CEO summary      │
│  /draft-linkedin-post → HITL social     │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  HUMAN-IN-THE-LOOP APPROVAL GATE        │
│  /Pending_Approval → human review       │
│  /Approved  → MCP executes action       │
│  /Rejected  → archived                  │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  EXECUTION — MCP Server (mcp_server.py) │
│  LinkedIn post via Playwright           │
│  Email send via Gmail API               │
│  Vault read/write/move tools            │
└─────────────────────────────────────────┘
```

## Bronze Tier Deliverables ✅

- [x] Obsidian vault with `Dashboard.md` and `Company_Handbook.md`
- [x] File watcher (`src/filesystem_watcher.py` — monitors /Inbox)
- [x] Claude Code reads from and writes to the vault via Agent Skills
- [x] Basic folder structure: `/Inbox`, `/Needs_Action`, `/Done`
- [x] Agent Skills: `/process-inbox`, `/update-dashboard`, `/daily-briefing`

## Silver Tier Deliverables ✅

- [x] **Gmail Watcher** (`src/gmail_watcher.py`) — polls Gmail inbox, converts priority emails to `.md` items in `/Needs_Action`; filters by labels, senders, and keywords
- [x] **LinkedIn Auto-posting** (`src/social_media_manager.py`) — Playwright-based LinkedIn automation with HITL approval gate; watches `/Approved/` for approved posts
- [x] **MCP Email Server** (`src/mcp_server.py`) — FastMCP server with 7 tools for vault operations and external action execution
- [x] **Email Watcher** (`src/email_watcher.py`) — watches `/Approved/` for `type: email_approval` items, sends via Gmail API, moves to Done, logs all actions
- [x] **Agent Skill: `/draft-linkedin-post`** — drafts posts from `/Needs_Action` tasks, saves to `/Pending_Approval` for human review
- [x] **Plan.md generation** — `/process-inbox` creates a structured `Plan.md` per task before routing to `/Pending_Approval` or `/Done`
- [x] **Human-in-the-Loop workflow** — full approval pipeline: `Needs_Action → Plans → Pending_Approval → Approved → Done`

---

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (or pip)
- Claude Code (active subscription)
- Obsidian v1.10.6+ (optional — vault works as plain folders)

### Install

```bash
cd alish-hackathon-0

# Install Python dependencies
uv sync

# For Gmail support
uv sync --extra gmail

# Copy environment template
cp .env.example .env
# Edit .env — fill in required credentials
```

### Environment Variables (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `VAULT_PATH` | Yes | Absolute path to `AI_Employee_Vault/` |
| `LINKEDIN_EMAIL` | Silver | LinkedIn login email |
| `LINKEDIN_PASSWORD` | Silver | LinkedIn login password |
| `LINKEDIN_SESSION_PATH` | Silver | Path to save Playwright session |
| `GMAIL_PRIORITY_SENDERS` | Gold | Comma-separated priority email senders |
| `GMAIL_PRIORITY_KEYWORDS` | Gold | Comma-separated priority subject keywords |

Gmail OAuth credentials (`gmail_credentials.json`) must be downloaded from Google Cloud Console and placed in the project root.

---

## Running the System

### File Watcher

```bash
# Dry-run (logs only, no file changes)
python src/filesystem_watcher.py --vault AI_Employee_Vault --dry-run

# Live mode
python src/filesystem_watcher.py --vault AI_Employee_Vault
```

### Gmail Watcher

```bash
python src/gmail_watcher.py --vault AI_Employee_Vault
# First run opens a browser for Google OAuth — token saved to .gmail_token.json
```

### Orchestrator (starts all watchers)

```bash
python src/orchestrator.py --vault AI_Employee_Vault
# Auto-starts Gmail watcher if gmail_credentials.json is present
```

### Email Watcher (HITL auto-send)

```bash
# Continuous mode — watches /Approved for email_approval items
python src/email_watcher.py --watch --vault AI_Employee_Vault

# One-shot send
python src/email_watcher.py --send FILENAME.md --vault AI_Employee_Vault

# Dry run
python src/email_watcher.py --watch --dry-run --vault AI_Employee_Vault
```

Or double-click `start_email_watcher.bat` on Windows.

### MCP Server

The MCP server starts automatically when Claude Code loads (configured in `.mcp.json`). To run it manually:

```bash
python src/mcp_server.py
```

### Claude Code Agent

```bash
# From the project root (where CLAUDE.md lives)
claude

# Agent Skills:
/process-inbox          # Reason about Needs_Action items, generate Plan.md, route to Pending_Approval or Done
/update-dashboard       # Refresh Dashboard.md with live folder stats
/daily-briefing         # Generate a dated CEO briefing in /Briefings/
/draft-linkedin-post    # Draft a LinkedIn post from a Needs_Action task → Pending_Approval
```

---

## Human-in-the-Loop Workflow

```
/Needs_Action/task.md
        │
        ▼ (Claude reasons, creates plan)
/Plans/task-plan.md
        │
        ▼ (requires approval)
/Pending_Approval/task.md
        │
   ┌────┴────┐
   ▼         ▼
/Approved  /Rejected
   │
   ▼ (MCP / watcher executes)
/Done
```

All sensitive actions (social posts, emails to new contacts, payments) are held in `/Pending_Approval` until a human moves the file to `/Approved`. Watchers detect the move and execute automatically.

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_vault_stats` | Count files per vault folder |
| `list_vault_folder(folder)` | List `.md` files in a folder |
| `read_vault_file(folder, filename)` | Read a vault file |
| `draft_linkedin_post(content, source)` | Save draft to `/Pending_Approval` |
| `move_vault_file(file, from, to)` | Advance workflow state |
| `execute_approved_post(filename)` | Post to LinkedIn via Playwright |
| `log_vault_action(type, data)` | Append to today's JSON audit log |

---

## Agent Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| `process-inbox` | `/process-inbox` | Reads Needs_Action, creates Plan.md, routes to Done or Pending_Approval |
| `update-dashboard` | `/update-dashboard` | Refreshes Dashboard.md stats from live folder counts |
| `daily-briefing` | `/daily-briefing` | Generates dated CEO briefing in /Briefings/ |
| `draft-linkedin-post` | `/draft-linkedin-post` | Drafts LinkedIn post from task, saves to /Pending_Approval |

---

## Folder Reference

| Folder | Purpose |
|--------|---------|
| `AI_Employee_Vault/Inbox/` | Raw file drops from watcher |
| `AI_Employee_Vault/Needs_Action/` | Items awaiting Claude reasoning |
| `AI_Employee_Vault/Plans/` | Claude-generated Plan.md per task |
| `AI_Employee_Vault/Done/` | Completed items |
| `AI_Employee_Vault/Pending_Approval/` | Awaiting human approval |
| `AI_Employee_Vault/Approved/` | Human-approved, pending execution |
| `AI_Employee_Vault/Rejected/` | Human-rejected items |
| `AI_Employee_Vault/Briefings/` | Daily CEO briefing reports |
| `AI_Employee_Vault/Logs/` | JSON audit logs (one file per day) |
| `AI_Employee_Vault/Accounting/` | Bank transactions and financial records |

---

## Credential Handling

- All credentials stored in `.env` (gitignored)
- `.env.example` provided as template
- No credentials ever stored in vault markdown files
- HITL approval required for all external actions (social, email)
- Gmail OAuth token saved to `.gmail_token.json` (gitignored)

---

## Roadmap

- **Bronze ✅** — Vault, file watcher, Claude Code Agent Skills
- **Silver ✅** — Gmail watcher, LinkedIn auto-posting, MCP server, email watcher, HITL workflow
- **Gold** — WhatsApp automation, Banking API, cron scheduling, Twitter/X, multi-platform social
- **Platinum** — Always-on cloud VM, Cloud+Local agent split, Odoo 24/7, Ralph Wiggum loop

---

*Built with Claude Code · Hackathon 0 · 2026*
