# AI Employee — Claude Code Configuration

This project is a **Personal AI Employee** built for Hackathon 0 (Bronze Tier).
Claude Code acts as the reasoning engine for an autonomous agent that manages tasks via an Obsidian vault.

## Vault Location

```
D:\alish-hackathon-0\AI_Employee_Vault\
```

## Folder Map

| Folder | Purpose |
|--------|---------|
| `Inbox/` | Raw file drops from the file watcher |
| `Needs_Action/` | Processed items ready for Claude's reasoning |
| `Plans/` | Claude-generated action plans (one per Needs_Action item) |
| `Done/` | Completed items (moved here after action is taken) |
| `Pending_Approval/` | Actions requiring human approval before execution |
| `Approved/` | Human-approved items ready for MCP execution |
| `Rejected/` | Human-rejected items (archived) |
| `Briefings/` | Daily/weekly CEO briefing reports |
| `Logs/` | JSON action logs (one file per day) |
| `Accounting/` | Bank transactions and financial records |

## Key Files

| File | Purpose |
|------|---------|
| `Dashboard.md` | Real-time system status — read this first |
| `Company_Handbook.md` | Rules of engagement — ALWAYS read before acting |
| `Business_Goals.md` | Q1 targets and active projects |

## Available Skills

Use these slash commands (via the Skill tool or `/skill-name`):

| Skill | Command | When to use |
|-------|---------|-------------|
| Process inbox items | `/process-inbox` | Items are waiting in /Needs_Action |
| Refresh dashboard | `/update-dashboard` | Dashboard stats may be stale |
| Generate daily briefing | `/daily-briefing` | Morning summary or status check |

## How to Start Processing

1. Read `Company_Handbook.md` (your rules)
2. Run `/process-inbox` to handle pending items
3. Run `/update-dashboard` to refresh stats
4. Run `/daily-briefing` for a summary

## Operating Rules

1. **Always read `Company_Handbook.md` before taking any action.**
2. **Never act on sensitive actions** (payments, emails to new contacts, social posts) without writing to `/Pending_Approval/` first.
3. **Log everything** — append to `/Logs/YYYY-MM-DD.json`.
4. **Dry run default** — if `DRY_RUN=true` in environment, log intent but don't write files outside the vault.
5. **Move files as state changes** — use file movement to track workflow state (Needs_Action → Plans → Pending_Approval → Approved → Done).

## Python Scripts

| Script | Purpose | Run |
|--------|---------|-----|
| `src/filesystem_watcher.py` | Watches /Inbox for new files | `python src/filesystem_watcher.py --vault AI_Employee_Vault` |
| `src/orchestrator.py` | Master process manager | `python src/orchestrator.py --vault AI_Employee_Vault` |

Install dependencies first:
```bash
uv sync
# or: pip install watchdog
```

## Security

- Credentials go in `.env` (see `.env.example`) — never in vault files
- `.env` is gitignored
- All external actions require human approval (HITL)
