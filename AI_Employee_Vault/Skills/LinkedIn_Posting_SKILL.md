---
name: linkedin-posting
version: 1.0
created: 2026-02-26
scripts:
  - src/social_media_manager.py
  - src/linkedin_oauth.py
launchers:
  - start_linkedin_watcher.bat
mcp_tools:
  - draft_linkedin_post
  - move_vault_file
  - execute_approved_post
claude_skill: /draft-linkedin-post
---

# Skill: LinkedIn Posting

Drafts, approves, and publishes LinkedIn posts using a Human-in-the-Loop (HITL) workflow.
Claude writes the draft — you approve — automation posts it.

**The post is NEVER published without a human moving the file to `/Approved/`.**

---

## Workflow Overview

```
User request / Needs_Action task
        │
        ▼
[Claude] /draft-linkedin-post skill
        │  draft_linkedin_post() MCP tool
        ▼
/Pending_Approval/SOCIAL_YYYYMMDD_linkedin_*.md
        │
        │  Human reviews draft
        │  Moves file to /Approved/
        ▼
/Approved/SOCIAL_YYYYMMDD_linkedin_*.md
        │
        │  start_linkedin_watcher.bat (watchdog)
        │  OR execute_approved_post() MCP tool
        ▼
LinkedIn post published  →  file moved to /Done/
```

---

## Step 1 — Trigger the Draft

### Option A: From a Needs_Action task
1. A file in `/Needs_Action/` contains a social media request
2. Run the Claude skill: `/draft-linkedin-post`
3. Claude reads `Company_Handbook.md` + `Business_Goals.md` for context
4. Claude crafts the post and saves it to `/Pending_Approval/`

### Option B: Direct request
Tell Claude what you want posted. Claude will draft and save directly to `/Pending_Approval/`.

### Option C: MCP tool directly
```
draft_linkedin_post(
    post_content = "Your post text here...",
    source_task_file = "source_task.md"
)
```

---

## Step 2 — Review the Draft

The draft file is saved to:
```
/Pending_Approval/SOCIAL_YYYYMMDD_HHmmss_linkedin_<task>.md
```

Open it in Obsidian or any text editor. The file contains:
- The full post text
- Character count (LinkedIn limit: 3000)
- Expiry time (24 hours)
- Approval instructions

**To edit:** Modify the post content directly in the file, then move to `/Approved/`.
**To approve:** Move the file to `/Approved/`.
**To reject:** Move the file to `/Rejected/`.

---

## Step 3 — Publish the Approved Post

### Auto (recommended) — run the watcher
```bat
start_linkedin_watcher.bat
```
Double-click the batch file. It watches `/Approved/` continuously and posts the moment you move a file there. Keeps running until you close the window.

### Manual — one-shot post
```bash
.venv\Scripts\python.exe src/social_media_manager.py --vault AI_Employee_Vault --post SOCIAL_YYYYMMDD_linkedin_task.md
```

### Via MCP tool
```
execute_approved_post(filename="SOCIAL_YYYYMMDD_linkedin_task.md")
```

---

## Post Content Rules (Company Handbook)

| Rule | Detail |
|------|--------|
| Length | 150–700 chars for feed posts; up to 3000 for long-form |
| Tone | Professional, authentic — not robotic or salesy |
| Hashtags | 3–5 relevant hashtags at the end |
| Hook | First line must grab attention (shows before "…see more") |
| No-go | Political content, competitor mentions, unverifiable claims |
| Emojis | Max 1–3, only where they add clarity |

---

## LinkedIn Poster Options

The script auto-selects the posting method:

| Method | When used | Setup needed |
|--------|-----------|-------------|
| **LinkedIn REST API** | `LINKEDIN_ACCESS_TOKEN` + `LINKEDIN_PERSON_URN` set in `.env` | Get token from LinkedIn Developer Portal |
| **Playwright browser** | No API token configured | `playwright install chromium` |

### Playwright first-time login
```bash
python src/linkedin_oauth.py
```
Saves a session cookie to `.linkedin_session.json` — subsequent runs skip the login screen.

---

## Dry Run (Safe Testing)

```bash
.venv\Scripts\python.exe src/social_media_manager.py --vault AI_Employee_Vault --watch --dry-run
```
Logs what *would* happen without posting anything. Use this to test the watcher setup.

---

## Environment Variables (`.env`)

```env
LINKEDIN_EMAIL=your@email.com
LINKEDIN_PASSWORD=your_password
LINKEDIN_SESSION_PATH=.linkedin_session.json
LINKEDIN_ACCESS_TOKEN=          # optional: REST API token
LINKEDIN_PERSON_URN=            # optional: urn:li:person:XXXXX
```

---

## File Naming Convention

| Stage | Pattern |
|-------|---------|
| Pending | `SOCIAL_YYYYMMDD_HHmmss_linkedin_<task_stem>.md` |
| Approved | same filename, moved to `/Approved/` |
| Done | same filename, moved to `/Done/` |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| "Playwright is not installed" | Run `playwright install chromium` |
| Login loop / CAPTCHA | Run `python src/linkedin_oauth.py` to save a fresh session |
| "File not found in /Approved" | Check spelling — filename must match exactly |
| Post published but file still in /Approved | Restart watcher; check `/Logs/` for errors |
| Character count too high | LinkedIn hard limit is 3000; edit the draft before approving |
