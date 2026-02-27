---
name: draft-linkedin-post
description: |
  Draft a LinkedIn post from a social media task in /Needs_Action and
  save it to /Pending_Approval for human review.
  Uses the HITL workflow: Claude drafts → human approves → Playwright posts.
  Use when there are social media tasks in /Needs_Action, or when the user
  asks you to write / draft a LinkedIn post.
---

# Draft LinkedIn Post

Read social media tasks from `/Needs_Action`, craft compelling LinkedIn post
drafts, and save them to `/Pending_Approval` for human review.

**The post will NOT be published until the human moves the file to `/Approved/`.**

---

## Step 1 — Read Context

Before drafting, read:
1. `Company_Handbook.md` — tone and social media rules
2. `Business_Goals.md` — current projects and messaging priorities
3. `Dashboard.md` — current system state

---

## Step 2 — Find Social Media Tasks

List all `.md` files in `/Needs_Action/` and identify social media tasks.

A file is a social task if:
- Its frontmatter contains `type: social_media`, `type: linkedin_post`, or `type: social_post`
- OR its body contains keywords like: `linkedin`, `social media`, `publish post`,
  `post on`, `announce`, `share on`, `write a post`

If no social tasks are found, report that to the user and stop.

---

## Step 3 — Draft the LinkedIn Post

For each social task, write an engaging LinkedIn post following these rules:

### Content Rules
- **Length:** 150–700 characters for feed posts; up to 3000 for long-form
- **Tone:** Professional, authentic, and human — not robotic or salesy
- **Structure:**
  - Hook (first line must grab attention — it appears before "…see more")
  - Body (story, insight, or value — use line breaks, not walls of text)
  - Call to action (question, invite comments, or link)
- **Hashtags:** 3–5 relevant hashtags at the end

### Things to NEVER do
- Mention competitors by name
- Make unverifiable claims
- Post anything political or controversial (Company Handbook rule)
- Use emojis excessively (1–3 max, only if they add clarity)

### Draft Format

Write the post as plain text exactly as it should appear on LinkedIn.
No markdown formatting inside the post body (LinkedIn ignores it).

---

## Step 4 — Save to Pending_Approval

Use the `draft_linkedin_post` MCP tool to save the draft:

```
draft_linkedin_post(
    post_content = "<the full post text>",
    source_task_file = "<filename from /Needs_Action>"
)
```

This creates a file in `/Pending_Approval/` with:
- The full post content
- Metadata (platform, char count, expiry)
- Clear approval instructions for the human

---

## Step 5 — Update Dashboard and Notify

After saving the draft:
1. Run `/update-dashboard` to refresh stats
2. Tell the user:
   - The draft filename in `/Pending_Approval/`
   - A preview of the post (first 200 chars)
   - How to approve: move the file to `/Approved/`
   - How to trigger posting: `python src/social_media_manager.py --vault AI_Employee_Vault --post <filename>`
   - Or to watch continuously: `python src/social_media_manager.py --vault AI_Employee_Vault --watch`

---

## Full Workflow Reminder

```
/Needs_Action/  ──[draft_linkedin_post MCP tool]──▶  /Pending_Approval/
                                                              │
                                          Human moves file   │
                                                              ▼
                                                        /Approved/
                                                              │
                                    social_media_manager.py  │
                                    (Playwright auto-posts)   │
                                                              ▼
                                                          /Done/
```
