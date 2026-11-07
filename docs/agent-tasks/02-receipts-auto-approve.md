# Task 02 — Receipt storage, payment history, and auto-approve

**Read first:** `AGENTS.md`, skill `payment-receipts`, skill `safe-change-workflow`, skill `rbac-tenancy` (scoping), `docs/ARCHITECTURE_NOTES.md` (sections E, F, G). If Task 01 is merged, use the adapter layer for panel calls.

## Context (from the owner)
Today the customer sends a receipt and waits; after approval nothing is stored and the message is deleted. Required:
1. **Store receipts.** In the database *and/or* keep the message in chat, so a receipt can be found later.
2. **Admin panel → مدیریت مشتریان:** per-customer list of previous payments with **date, amount and the receipt image**.
3. **Auto-approve ("تایید خودکار")** — a setting the admin can enable. When on: the receipt is approved at once, the subscription is created and delivered.
   Later the admin may confirm (nothing more happens) or reject (fake receipt) → the subscription is **deleted or disabled** and the customer is told it was deactivated.
   Purpose: the customer doesn't wait while the admin is busy.

## Phase 1 — Research (read-only)
Trace the current flow end to end and write the findings (with `path::symbol`) at the top of your plan:
receipt received → forwarded to whom → buttons → approve/reject → order fulfilment → where the message is deleted → what is persisted today.
Find where per-admin/seller settings live and how the settings screen is rendered.

## Phase 2 — Plan and gate
Include: tables/columns/migration, state machine, handler changes (files), settings toggle placement, admin UI callbacks, retry job for revocation, test list.
Ask these in one batch (Persian), each with a default:
1. Auto-approve **per reviewer** (the seller/admin a customer is attached to) or **global**? *Default: per reviewer.*
2. On reject-after-auto-approve: **disable** or **delete** the subscription? *Default: disable.*
3. Auto-approve for **renewals and wallet top-ups** too? *Default: no — only new subscription purchases; others stay manual.*
4. Keep an additional copy of receipts in a private archive channel? *Default: no.*
5. Is the customer message text OK? «اشتراک شما غیرفعال شد، چون پرداخت تایید نشد…» *Default: yes.*

`⛔ منتظر تایید شما هستم` — no file-modifying tool calls until the owner replies. Record answers in `docs/DECISIONS.md`.

## Phase 3 — Implement
1. Migration + models: `payments`, `payment_events`, reviewer setting `auto_approve_receipts`.
2. Service: `transition()` (conditional update + event), `submit_receipt()`, `approve()`, `reject()`, `auto_approve()`, `confirm_auto()`, `reject_auto()` (→ `revoke_pending` → adapter disable → `rejected`), retry job for `revoke_pending` (APScheduler, idempotent).
3. Handlers: customer receipt submission persists first; reviewer message **edited** (not deleted) on decision; buttons for auto-approved receipts.
4. Admin UI: «💳 پرداخت‌ها» under the customer, pagination, «نمایش فیش», scope-checked per actor.
5. Settings toggle «⚡ تایید خودکار فیش» with explanation.
6. Backfill: none (history starts now). State this in the report.

## Constraints
- Amounts: same type/unit as the codebase. No floats.
- No panel call inside a DB transaction. Notifications are sent only after the transition committed, once.
- Do not change RBAC rules in this task beyond using the scoping helper (if Task 03 isn't done yet, scope by the existing mechanism and note it).
- Do not remove the existing manual flow; it is the default.

## Acceptance criteria
- [ ] A receipt sent while the panel is down is still persisted and visible in history.
- [ ] Manual approve/reject unchanged for customers; the reviewer message remains in chat with final status.
- [ ] Auto-approve ON: subscription delivered exactly once; reviewer sees receipt + two buttons; confirm → `approved`; reject → disabled on panel, customer notified once, status `rejected`.
- [ ] Panel failure on revoke → `revoke_pending`, retry job completes later, no duplicate notifications.
- [ ] Two simultaneous reviewer taps → exactly one succeeds; the other gets «قبلاً بررسی شده».
- [ ] History list: 5 per page, correct scope for owner/seller, expired `file_id` handled.
- [ ] Migration round-trip OK; `ruff` + `pytest` OK.

## Self-check before answering
Is the payment row committed before any side effect? Can a retry send the subscription twice? Can a seller open another seller's receipt via a crafted callback?

Final report: `AGENTS.md` §6, plus a state-transition table of what you implemented.
