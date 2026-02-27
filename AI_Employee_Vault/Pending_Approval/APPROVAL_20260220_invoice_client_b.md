---
type: approval_request
action: invoice_and_email_send
client: Client B
created: 2026-02-20T02:20:00
expires: 2026-02-21T02:20:00
status: pending
priority: high
source_plan: PLAN_20260220_invoice_client_b.md
source_item: FILE_20260220_021306_client_b_message.md
---

# Approval Required — February Invoice for Client B

## Proposed Action
Generate a **February 2026 invoice** for **Client B** and send it via email.

## What Triggered This
File dropped in Inbox: `client_b_message.txt`
> "Client B says: please send me an invoice for February work"

Keyword **"invoice"** detected → escalated to HIGH priority per Company Handbook.

## Information Needed from You

Before this can proceed, please fill in the following:

| Field | Value |
|-------|-------|
| Client B's email address | _(fill in)_ |
| Invoice amount | _(fill in e.g. $2,000)_ |
| Breakdown of "February work" | _(fill in line items or description)_ |
| Invoice number | _(fill in e.g. INV-002)_ |
| Payment due date | _(fill in e.g. Net 30)_ |

## Why Approval Is Required
Per **Company Handbook — Communication Rules**:
> "Reply to known contacts: Auto-draft, require human approval to send."

Per **Company Handbook — Financial Rules**:
> "Flag any payment over $100 for mandatory human approval."

This involves generating and sending a financial document to an external client — **always requires explicit human approval**.

---

## To Approve
1. Fill in the required information above
2. Move this file to `/Approved/` folder
3. Claude will generate the invoice and send the email

## To Reject
Move this file to `/Rejected/` folder.

---
*Expires: 2026-02-21 02:20 — item will be flagged as overdue after this time*
