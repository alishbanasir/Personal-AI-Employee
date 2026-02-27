---
name: process-inbox
description: |
  Process items in the AI Employee vault's /Needs_Action folder.
  Reads each pending .md file, reasons about what action is needed,
  creates a Plan.md file, and either moves the item to /Done (if no
  approval required) or to /Pending_Approval (if human review needed).
  Use when there are unprocessed items in the /Needs_Action folder.
---

# Process Inbox

Read all pending items in `/Needs_Action`, reason about each one using `Company_Handbook.md` as your guide, and take the appropriate action.

## Step 1 — Read Context

Before processing any item, read:
1. `Company_Handbook.md` — your rules of engagement
2. `Dashboard.md` — current system state
3. `Business_Goals.md` — active projects and targets

## Step 2 — Scan Needs_Action

List all `.md` files in `/Needs_Action/` (excluding `.gitkeep`).

For each file:
1. Read the file completely
2. Classify the item (email, file_drop, whatsapp, task, etc.)
3. Determine priority (high/medium/low) per Company_Handbook rules
4. Decide: can Claude act autonomously, or does this need human approval?

## Step 3 — Create Plan File

For each item, create a corresponding Plan file in `/Plans/`:

```markdown
---
created: <ISO timestamp>
source_file: <original filename in Needs_Action>
status: pending
requires_approval: <true|false>
priority: <high|medium|low>
---

## Objective
<One-sentence description of what needs to happen>

## Steps
- [x] Read and classify item
- [x] Identify required action
- [ ] <Next step>
- [ ] <Next step>
- [ ] Complete and move to /Done

## Decision
<Explain your reasoning: why approval is or isn't required>
```

## Step 4 — Route the Item

### If NO approval required (low-risk, routine task):
- Complete any file-only actions (tagging, categorizing, summarizing)
- Move the original item from `/Needs_Action/` to `/Done/`
- Move the Plan file to `/Done/` after completing all steps
- Update `Dashboard.md` Recent Activity section

### If approval IS required (external action, payments, emails, etc.):
- Create an approval request file in `/Pending_Approval/`:

```markdown
---
type: approval_request
action: <email_send|payment|social_post|other>
created: <ISO timestamp>
expires: <24h from now>
status: pending
source_plan: <Plan filename>
---

## Proposed Action
<Clear description of what will happen if approved>

## Details
<Relevant details: recipient, amount, content, etc.>

## To Approve
Move this file to `/Approved/` folder.

## To Reject
Move this file to `/Rejected/` folder.
```

- Leave the original item in `/Needs_Action/` until approval is given
- Update `Dashboard.md` Pending Items table

## Step 5 — Update Dashboard

After processing all items, update `Dashboard.md`:
- Refresh the **Pending Items** table
- Add entries to **Recent Activity**
- Update **Quick Stats** counts

## Rules

- Always read `Company_Handbook.md` before deciding on autonomy level
- Never send emails, make payments, or post to social media without approval
- Log every action reasoning in the Plan file
- If an item is ambiguous, route it to `/Pending_Approval/` rather than acting
- Prefer doing less autonomously over risking an unwanted action
