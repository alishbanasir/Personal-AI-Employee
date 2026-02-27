# Personal AI Employee — Bronze Tier

**Hackathon 0: Building Autonomous FTEs in 2026**
**Tier:** Bronze (Foundation)

A local-first, agent-driven Personal AI Employee powered by Claude Code and an Obsidian vault.

---

## Architecture

```
External Sources
      │
      ▼
┌─────────────────┐
│  PERCEPTION     │  filesystem_watcher.py monitors /Inbox
│  File Watcher   │  → creates .md items in /Needs_Action
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│  OBSIDIAN VAULT (Local)         │
│  /Inbox  /Needs_Action  /Done   │
│  /Plans  /Pending_Approval      │
│  Dashboard.md  Company_Handbook │
└────────┬────────────────────────┘
         │
         ▼
┌─────────────────┐
│  REASONING      │  Claude Code + Agent Skills
│  Claude Code    │  /process-inbox, /update-dashboard
└────────┬────────┘  /daily-briefing
         │
         ▼
┌─────────────────┐
│  HUMAN-IN-LOOP  │  /Pending_Approval → /Approved → Done
│  Approval Gate  │  (MCP execution — Silver/Gold tier)
└─────────────────┘
```

## Bronze Tier Deliverables ✅

- [x] Obsidian vault with `Dashboard.md` and `Company_Handbook.md`
- [x] One working Watcher script (`src/filesystem_watcher.py` — file system monitoring)
- [x] Claude Code reads from and writes to the vault via Agent Skills
- [x] Basic folder structure: `/Inbox`, `/Needs_Action`, `/Done`
- [x] All AI functionality implemented as Agent Skills (`/process-inbox`, `/update-dashboard`, `/daily-briefing`)

## Setup

### Prerequisites

- Python 3.13+
- [uv](https://github.com/astral-sh/uv) (or pip)
- Claude Code (active subscription)
- Obsidian v1.10.6+ (optional — vault works as plain folders)

### Install

```bash
# Clone / open in Claude Code
cd alish-hackathon-0

# Install Python dependencies
uv sync
# or: pip install watchdog

# Copy environment template
cp .env.example .env
# Edit .env — set VAULT_PATH at minimum
```

### Run the File Watcher

```bash
# Safe dry-run mode (logs only, no file changes)
python src/filesystem_watcher.py --vault AI_Employee_Vault --dry-run

# Live mode
python src/filesystem_watcher.py --vault AI_Employee_Vault
```

### Run the Orchestrator (starts watcher + monitors vault)

```bash
python src/orchestrator.py --vault AI_Employee_Vault
```

### Use Claude Code to process items

```bash
# From the project root (where CLAUDE.md lives)
claude

# Then use skills:
/process-inbox      # Process items in /Needs_Action
/update-dashboard   # Refresh Dashboard.md stats
/daily-briefing     # Generate today's CEO briefing
```

### Test the watcher

1. Drop any file into `AI_Employee_Vault/Inbox/`
2. The watcher creates a `.md` action file in `AI_Employee_Vault/Needs_Action/`
3. Run `/process-inbox` in Claude Code to reason about it

## Credential Handling

- All credentials stored in `.env` (gitignored)
- `.env.example` provided as template
- No credentials ever stored in vault markdown files
- HITL (Human-in-the-Loop) approval required for all external actions

## Folder Reference

| Folder | Purpose |
|--------|---------|
| `AI_Employee_Vault/Inbox/` | Raw file drops |
| `AI_Employee_Vault/Needs_Action/` | Items awaiting Claude reasoning |
| `AI_Employee_Vault/Plans/` | Claude-generated action plans |
| `AI_Employee_Vault/Done/` | Completed items |
| `AI_Employee_Vault/Pending_Approval/` | Awaiting human approval |
| `AI_Employee_Vault/Approved/` | Human-approved, pending MCP execution |
| `AI_Employee_Vault/Briefings/` | Daily CEO briefing reports |
| `AI_Employee_Vault/Logs/` | JSON audit logs |

## Agent Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| `process-inbox` | `/process-inbox` | Reads Needs_Action, creates Plans, routes to Done or Pending_Approval |
| `update-dashboard` | `/update-dashboard` | Refreshes Dashboard.md stats from live folder counts |
| `daily-briefing` | `/daily-briefing` | Generates dated CEO briefing in /Briefings/ |

## Roadmap

- **Silver:** Gmail Watcher + LinkedIn posting + MCP email server + cron scheduling
- **Gold:** Full cross-domain integration, Odoo accounting, Ralph Wiggum loop, weekly audit
- **Platinum:** Always-on cloud VM, Cloud+Local agent split, Odoo 24/7

---

*Built with Claude Code · Hackathon 0 · 2026*
