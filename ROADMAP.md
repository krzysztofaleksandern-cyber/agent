# ROADMAP — toward replacing ~95% of an office

> Status: blocks for email, calendar, scheduler, audit, knowledge base, operator vision,
> CRM + web leads and the kill switch are **built** (phases 16–23). What remains below needs
> external accounts/OAuth (cloud files, accounting, e-signature, Twilio) or a product decision.

The platform already gives you: a chief-of-staff agent (Jarvis), control of your own PC, a
secretary, a coder, a writer, an auditor, a researcher, sales and support agents, background
jobs, a scheduler, approvals, a kill switch, memory, self-learning, a company knowledge base,
email, calendar and CRM, plus your local voice (VoiceStudio). Below is what remains to cover a
real office, ordered by value-for-effort. Items marked ✅ are already built.

Legend: ⭑ high value / low effort · ◆ needs an external integration/connector · ⚠ sensitive.

## A. Connect the office tools (biggest leverage)
- ✅ **Email** (done, phase 16) (IMAP/SMTP or Gmail/Graph API): read, draft, reply, file. Secretary gets a
  real inbox instead of driving the mail app on screen.
- ✅ **Calendar** (done, phase 17 — local + .ics export) (CalDAV / Google / Microsoft): read availability, create/move meetings.
- ◆ **Cloud files** (Google Drive / OneDrive / Dropbox): find, read, write documents.
- ◆ **Messaging** (Slack/Telegram/WhatsApp inbound): Jarvis answers and acts from chat.
- ◆ **Accounting/invoicing** (e.g. Fakturownia/wFirma API): draft invoices, reconcile ⚠.
- Each becomes a **tool** behind the existing tool interface + an **approval rule** for
  anything that sends, pays or deletes.

## B. Documents & knowledge
- ⭑ **Office documents**: generate .docx/.xlsx/.pptx and PDFs (writer + a template engine).
- ✅ **Company knowledge base** (done, phase 20): index your files/wiki into the existing RAG memory so every
  agent answers with your real policies, prices and templates.
- ◆ **E-signature** (DocuSign/Autenti) ⚠ — send contracts for signature on approval.
- **OCR + inbox for paper/scans/receipts** → structured data → accounting.

## C. Make the agents reliable at scale
- ⭑ **Multi-worker queue + priorities**: run several tasks at once (today it's one worker).
- ⭑ **Persistent approvals** (survive restart) and an **audit log** of every action ⚠.
- ✅ **Scheduler** (done, phase 19): recurring jobs (daily inbox triage, weekly reports, month-end invoicing).
- **Per-agent tool permissions & spending caps** (e.g. operator can't exceed X, secretary
  can send to known contacts only) ⚠.
- **Vision for the operator**: a local vision model (e.g. Qw2-VL/Llama-Vision in Ollama) so
  it truly *sees* the screen instead of working blind — big reliability jump for desktop use.

## D. Customer-facing
- ◆ **Phone/voice line** (Twilio + your STT + VoiceStudio): Jarvis answers calls, books,
  takes messages. You already have the voice half.
- ✅ **Website leads** (done, phase 22 — POST /v1/leads) on stacklogic.pl / nexum-holding: a client agent that answers,
  qualifies and files leads into CRM.
- ✅ **CRM** (done, phase 22) (HubSpot/Pipedrive or a local one): contacts, deals, follow-ups.

## E. Specialist office agents (mostly just prompts + the tools above)
- **bookkeeper** — invoices, expenses, reminders, month-end (needs accounting tool).
- **sales** — leads, proposals, follow-ups (needs CRM + email).
- **support** — answers tickets/chat from the knowledge base.
- **hr/admin** — contracts, onboarding checklists, scheduling.
- **analyst** — pulls numbers (sheets/DB), builds the weekly dashboard.

## F. Safety & trust (do these alongside, not last) ⚠
- ✅ Full **audit trail** (done, phase 18) + daily summary (todo).
- **Dry-run mode** for new automations before they act for real.
- ✅ hard **kill switch** (done, phase 23); spending/rate caps (todo).
- Regular **backups off the VPS** and a tested restore.

---

### Suggested order
1. Email + calendar + files connectors (A) → secretary becomes genuinely useful.
2. Scheduler + multi-worker + audit log (C) → it runs the routine without you.
3. Knowledge base in RAG + document generation (B) → consistent, on-brand output.
4. Operator vision (C) → desktop automation stops breaking.
5. Customer-facing voice/chat + CRM (D) → it starts replacing front-office too.

Each item is a new **tool** and/or an **agent profile** on the existing architecture — so it
stays modular, testable and private. Tell me which block to build next and I'll do it in
phases, tests-first, like the rest.
