---
created: 2026-02-20T02:20:00
source_file: INBOX_20260220_invoice_client_a.md
status: pending_approval
requires_approval: true
priority: high
---

## Objective
Generate a draft invoice for Client A and send it via email — pending human approval.

## Steps
- [x] Read and classify item
- [x] Identify client: Client A
- [x] Detect keyword "invoice" → escalate to HIGH priority
- [x] Determine action: draft invoice + email send
- [ ] Human approves → generate invoice PDF/document
- [ ] Human approves → send via email MCP
- [ ] Log transaction in /Accounting/
- [ ] Move to /Done

## Decision
**Approval REQUIRED.**

Reasoning per Company Handbook:
- Contains keyword "invoice" → HIGH priority.
- Sending an email (invoice delivery) always requires human approval, even to known contacts.
- No invoice amount, client email address, or period specified — these must be confirmed by human before dispatch.
- Per Financial Rules: any invoice action involves potential payment, so extra caution applies.

## What's Missing (Human must supply before action)
- [ ] Client A's email address
- [ ] Invoice amount / service details
- [ ] Invoice period (month/project)
- [ ] Invoice number / reference

## Approval Request
See: `/Pending_Approval/APPROVAL_20260220_invoice_client_a.md`
