---
created: 2026-02-20T02:20:00
source_file: FILE_20260220_021306_client_b_message.md
status: pending_approval
requires_approval: true
priority: high
---

## Objective
Generate a draft invoice for Client B for February work and send via email — pending human approval.

## Steps
- [x] Read and classify item
- [x] Identify client: Client B
- [x] Detect keyword "invoice" → escalate to HIGH priority
- [x] Determine action: draft February invoice + email send
- [ ] Human approves → generate invoice for "February work"
- [ ] Human approves → send via email MCP
- [ ] Log transaction in /Accounting/
- [ ] Move to /Done

## Decision
**Approval REQUIRED.**

Reasoning per Company Handbook:
- Contains keyword "invoice" → HIGH priority.
- Message explicitly asks for "invoice for February work" — external email action required.
- Company Handbook: "Reply to known contacts: Auto-draft, require human approval to send."
- Financial Rules: Invoice generation implies payment — mandatory approval threshold applies.
- Client B's email is unknown — cannot send without human confirming recipient.

## What's Missing (Human must supply before action)
- [ ] Client B's email address
- [ ] February invoice amount / rate
- [ ] Invoice number / reference
- [ ] Any specific line items for "February work"

## Approval Request
See: `/Pending_Approval/APPROVAL_20260220_invoice_client_b.md`
