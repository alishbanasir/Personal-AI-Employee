---
type: approval_request
action: invoice_and_email_send
client: Client A
created: 2026-02-20T02:20:00
expires: 2026-02-21T02:20:00
status: pending
priority: high
source_plan: PLAN_20260220_invoice_client_a.md
source_item: INBOX_20260220_invoice_client_a.md
---

# Approval Required — Invoice for Client A

## Proposed Action
Generate an invoice for **Client A** and send it via email.

## What Triggered This
File dropped in Inbox: `invoice_test.txt`
> "Test invoice from Client A - please process"

Keyword **"invoice"** detected → escalated to HIGH priority per Company Handbook.

## Information Needed from You

Before this can proceed, please fill in the following:

| Field | Value |
|-------|-------|
| Client A's email address | _(fill in)_ |
| Invoice amount | _(fill in e.g. $1,500)_ |
| Invoice period / service | _(fill in e.g. "February 2026 consulting")_ |
| Invoice number | _(fill in e.g. INV-001)_ |
| Payment due date | _(fill in e.g. Net 30)_ |

## Why Approval Is Required
Per **Company Handbook — Communication Rules**:
> "Reply to known contacts: Auto-draft, require human approval to send."

Sending an invoice email is an **irreversible external action**. Claude will not dispatch it without explicit approval.

---

## To Approve
1. Fill in the required information above
2. Move this file to `/Approved/` folder
3. Claude will generate the invoice and send the email

## To Reject
Move this file to `/Rejected/` folder.

---
*Expires: 2026-02-21 02:20 — item will be flagged as overdue after this time*
