---
name: update-dashboard
description: |
  Refresh Dashboard.md with current vault statistics and activity.
  Counts items in each folder, updates the Quick Stats section,
  and ensures the Recent Activity table reflects the latest state.
  Use after processing items or when Dashboard.md may be stale.
---

# Update Dashboard

Scan the vault and rewrite `Dashboard.md` with accurate, current information.

## What to Count

Scan these folders and count non-.gitkeep `.md` files:

| Folder | Dashboard field |
|--------|-----------------|
| `/Inbox/` | Inbox items |
| `/Needs_Action/` | Needs Action |
| `/Pending_Approval/` | Pending approval |
| `/Done/` (files modified today) | Done today |

## What to Update

1. **Quick Stats block** — replace all four counts with live values
2. **Pending Items table** — rebuild from actual `/Needs_Action/` contents:
   - List filename, type (from frontmatter), priority, and age
   - Sort by priority (high first), then by creation time (oldest first)
3. **System Status** — mark each component as 🟢/🟡/🔴 based on folder health

## Dashboard.md Format

Keep the exact structure of `Dashboard.md`. Only update values inside these sections:
- `## System Status` table
- `## Pending Items` table
- `## Recent Activity` table (prepend new rows, keep last 10)
- `## Quick Stats` block

## Output

After updating, confirm:
```
Dashboard.md updated:
  - Inbox: <N> items
  - Needs Action: <N> items
  - Pending Approval: <N> items
  - Done today: <N> items
```
