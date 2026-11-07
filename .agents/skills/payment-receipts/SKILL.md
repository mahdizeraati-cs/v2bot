---
name: payment-receipts
description: Playbook for payment receipts (فیش) in the store bot — persisting receipts in the database, per-customer payment history in the admin panel, keeping the receipt message in the review chat, and the per-reviewer "auto-approve" mode (deliver the subscription immediately, let the admin confirm or reject later and revoke on reject). Use this skill whenever a task touches receipts/رسید/فیش, card-to-card payment approval, payment history, order fulfilment after payment, auto-approve/تایید خودکار, or revoking a subscription after a rejected receipt.
---

# Payment receipts and auto-approve

## Current behaviour (from the owner)
The customer sends a receipt photo and waits. After approval the receipt is not stored anywhere — the message is deleted.
Goal: keep a durable record (DB + chat), show history per customer to the right admin, and add a per-reviewer auto-approve mode.

## Principles
- **Persist first.** Create the `Payment` row (status `pending`) before any other side effect. A crash after that point must not lose the receipt.
- **State machine, not booleans.** Every transition is a conditional UPDATE and writes an event row. Two taps or two reviewers cannot both succeed.
- **Panel calls are outside DB transactions** (see AGENTS.md §3). Revocation is a two-step state (`revoke_pending` → `rejected`) so a panel outage cannot leave DB and panel disagreeing silently.
- **Storage of the image = Telegram `file_id` + metadata**, not a blob in PostgreSQL. `file_id` is bot-specific and not guaranteed forever, so also keep the review-chat message reference and handle "file no longer available" gracefully.

## Data model (propose in plan; Alembic migration; adapt names/types to the codebase — money type must match existing convention)

`payments`
- `id`, `customer_id` (FK), `reviewer_id` (FK — the seller/admin the customer is assigned to), `order_id` (FK, nullable),
- `amount` (integer smallest unit, expected price of the plan), `currency`/unit as in codebase,
- `status` — `pending | auto_approved | approved | rejected | revoke_pending`,
- `auto_approved` (bool, true if the delivery happened before human review),
- `tg_file_id`, `tg_file_unique_id`, `file_sha256` (nullable; only if you download the file — catches exact re-uploads),
- `chat_id`, `message_id` (the copy in the reviewer's chat), `caption`,
- `submitted_at`, `reviewed_at`, `reviewed_by`, `review_note`,
- indexes: `(customer_id, submitted_at DESC)`, `(status)`, `(tg_file_unique_id)`.

`payment_events` — `payment_id`, `from_status`, `to_status`, `actor_id` (null = system), `at`, `note`. Append-only.

Reviewer setting: `auto_approve_receipts` (bool, default false) stored with the reviewer's own settings (seller/admin/owner record) — find how settings are stored today and follow it.

## State machine

```
pending ──approve (manual)────────────► approved
pending ──reject  (manual)────────────► rejected          (notify customer)
pending ──[auto-approve ON]───────────► auto_approved     (subscription delivered immediately)
auto_approved ──admin confirms────────► approved
auto_approved ──admin rejects─────────► revoke_pending ──panel disable ok──► rejected
revoke_pending ──panel failed─────────► stays revoke_pending (retry job + alert), never silently dropped
```

Implementation notes:
- Transition helper: `async def transition(session, payment_id, expected, new, actor_id, note) -> bool` using
  `UPDATE payments SET status=:new, reviewed_at=now(), reviewed_by=:actor WHERE id=:id AND status=:expected RETURNING id`.
  `False` → answer the callback with "این فیش قبلاً توسط <نام> بررسی شده".
- Auto-approve happens in the same handler that receives the photo, **after** the row is committed: transition `pending→auto_approved` → fulfil the order
  through the adapter → send the subscription to the customer → send the receipt + buttons to the reviewer.
  If fulfilment fails (panel down) keep `auto_approved` with the order `failed_retryable` and alert the reviewer; do not revert to `pending` silently.
- Reject-after-auto-approve default action is **disable** (reversible, keeps usage history) — **ask the owner** (disable vs delete).
  Message to the customer: «اشتراک شما غیرفعال شد، چون پرداخت تایید نشد. در صورت اشتباه با پشتیبانی تماس بگیرید.» (owner may edit the text).
- v1 scope of auto-approve = **purchase of a new subscription**. Renewals and wallet top-ups follow the manual flow unless the owner decides otherwise
  (reverting a renewal or a spent top-up needs extra rules). Say this in the plan.

## Review-chat behaviour ("stays in chat")
Do not delete the receipt message in the reviewer chat. After a decision **edit** it: append «✅ تایید شد توسط X — تاریخ» or «❌ رد شد…» and remove the buttons.
Auto-approved receipts show buttons `✅ تایید نهایی` and `❌ رد و غیرفعال‌سازی`.
Non-blocking duplicate hint: if another payment with the same `file_unique_id` (or `file_sha256`) exists, show «⚠️ فیش مشابه قبلاً ثبت شده» to the reviewer.

## Admin UI: مدیریت مشتریان → مشتری → «💳 پرداخت‌ها»
- Paginated list, 5 per page, newest first: date, amount, status emoji, button «نمایش فیش».
- Callback data stays ≤ 64 bytes, e.g. `pay:l:{customer_id}:{page}` and `pay:v:{payment_id}`.
- «نمایش فیش» sends the photo by `file_id` with caption (amount, date, status, reviewer). On `TelegramBadRequest` show «فایل دیگر در دسترس نیست» — never crash.
- **Scope**: a seller sees only their own customers' payments; the owner sees all; admins per the permission matrix (see `rbac-tenancy`). Re-check ownership on every callback (IDOR).
- Dates: use the project's existing date helper (Jalali if already used).

## Settings UI
A toggle «⚡ تایید خودکار فیش» in the reviewer's settings with a short explanation of the risk and the revoke behaviour, status shown as 🟢/🔴.
Toggling is an audited event.

## Tests (minimum)
- pending→approved/rejected; double approve → second returns "already reviewed".
- Auto-approve ON: subscription delivered once; reviewer gets buttons; confirm → `approved`; reject → `revoke_pending` → panel disable called once → `rejected` + customer notified.
- Panel disable fails → stays `revoke_pending`, retry job succeeds later, no double notification.
- Receipt persisted even if panel is down; history list scoped per role; `file_id` send failure handled.
- Concurrency: two simultaneous approvals → exactly one succeeds.

## Pitfalls
- Deleting/forwarding the receipt before the DB commit.
- Using `float` amounts; parsing amounts from captions.
- Notifying the customer twice on retries (make notifications part of the transition, guarded by its success).
- Letting the revoke job run against a server whose `panel_type` was changed meanwhile — resolve the adapter at execution time from the order's server.
