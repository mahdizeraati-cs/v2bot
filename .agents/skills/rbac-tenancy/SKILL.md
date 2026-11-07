---
name: rbac-tenancy
description: Playbook for roles, permissions and multi-seller tenancy in the store bot — owner / admin / seller / customer, the round-robin assignment of customers to sellers, scoped queries, owner-level broadcast to every customer in the hierarchy, forced channel join (جوین اجباری) inheritance, and callback authorization (IDOR) checks. Use this skill whenever a task touches permissions/دسترسی, owner vs seller vs admin behaviour, broadcast/پیام همگانی, forced join, customer assignment, or any admin handler that reads or modifies another user's data.
---

# Roles, tenancy and hierarchy

## The model (as described by the owner — confirm against the code)
- **Owner** is the root. **Sellers/admins** work under the owner. **Customers** are each attached to exactly one seller/admin.
- Attachment is **round-robin**. If the owner is the only seller, every customer attaches to the owner.
- Owner-level actions must reach the **whole subtree**: a broadcast or a forced-join channel set by the owner applies to every customer of every seller/admin under them.
  Currently it does not: the owner's broadcast reaches only a subset, and the forced join is not applied to all customers. Find the query/filter that scopes too narrowly.

Never assume how roles are stored. Find out (`OWNER_ID`, role columns/tables, admin tables) and write it in `docs/rbac_audit.md`.

## Root-cause hunting (broadcast / forced join)
Typical causes — check each: recipient query filtered by `seller_id == actor.id` (so the owner only reaches customers attached to the owner);
forced-join stored per seller and read only from the customer's seller; broadcast skipping `blocked`/`inactive` incorrectly; handler registered only on the user router;
membership check implemented inside some handlers instead of one middleware.

## Design rules
1. **One scoping helper.** All "which customers/payments/servers may this actor see?" questions go through a single function/query-builder, e.g.
   `customers_visible_to(actor)`: owner → all; seller → own customers; admin → per decision. Handlers never hand-write the filter.
2. **Default deny.** A `Role` enum + `require_role(...)` filter. Every admin callback/command declares who may call it. No declaration → denied.
3. **Authorise the object, not just the role.** For `callback_data` carrying an ID (`user:ban:123`) verify the object is inside `customers_visible_to(actor)` — a crafted callback must fail.
4. **Broadcast** = recipients query (scoped by the same helper, plus staff if the owner decides) → background task →
   rate-limited send (≤ 25 msg/s) → handle `TelegramRetryAfter`, `TelegramForbiddenError` (mark unreachable) → progress message to the sender → final stats
   (sent / blocked / failed). One recipient list = a set of unique chat IDs.
5. **Forced join** = effective channels for a customer = owner-level channels ∪ their seller's channels. Enforce in **one middleware/filter** in front of all customer routers.
   Use `getChatMember`, cache the result briefly (≈ 60 s), and **fail open** with an alert to the setter when the bot is not admin in the channel or Telegram errors — a misconfigured channel must not lock every customer out.
   Allow `/start` to show the join prompt and a «✅ عضو شدم» re-check button.
6. **Round-robin must be correct under concurrency.** Keep the cursor in the database and advance it atomically
   (`SELECT … FOR UPDATE` on the cursor row or an atomic counter) — never in process memory. Skip inactive/blocked sellers. Assignment is sticky: adding a seller later does not reassign existing customers.

## Audit procedure (read-only first)
Produce `docs/rbac_audit.md` with:
1. **Role map** — how each role is identified (file::symbol).
2. **Handler inventory** — every admin/owner-facing command and callback. One row each:

   | Handler (file::func) | Trigger | Who can call today | Data scope today | Problem |
   |---|---|---|---|---|
   | `admin_handlers.py::broadcast_send` | `broadcast:send` | any admin (no role filter) | customers where seller_id = actor | owner misses customers of other sellers |

3. **Assignment algorithm review** — where it lives, where the cursor is stored, behaviour with: one seller (owner only), two sellers, a new seller added, a seller disabled, concurrent `/start` from many users, user who already has a seller.
4. **Broadcast and forced-join review** — exact code paths and why they do not cover the subtree.
5. **Findings** ranked by severity (privilege escalation / IDOR > data leak > wrong behaviour > cosmetic).
6. **Proposed permission matrix** (below) with a default for every cell, and the questions the owner must answer.

## Proposed permission matrix (defaults to propose, not to implement before the owner answers)

| Capability | Owner | Admin | Seller |
|---|---|---|---|
| Global bot settings, backups, logs | ✅ | ❌ | ❌ |
| Register/edit servers (panels) | ✅ | ? | ? |
| Plans and prices | ✅ | ? | own only? |
| Manage sellers/admins | ✅ | ❌ | ❌ |
| View/manage customers | all | ? | own |
| Review receipts / payment history | all | ? | own |
| Auto-approve toggle | ✅ | ✅ (own scope) | ✅ (own scope) |
| Broadcast | whole subtree | ? | own customers |
| Forced-join channels | global (subtree) | ? | own customers |
| Financial stats | all | ? | own |

Rows with `?` are real questions for the owner. Ask them in one batch, in Persian, each with your proposed default, then record the answers in `docs/DECISIONS.md`.

## Tests (minimum fixture)
Owner `O`, sellers `S1`, `S2`, admin `A1`, customers `C1…C6` spread across them.
- `O` broadcasts → all six customers (+ staff if decided); `S1` broadcasts → only `S1`'s customers.
- `O` forced channel X → required for all six; `S1`'s channel Y → required only for `S1`'s customers; effective = union.
- Seller `S1` crafts a callback for a `S2` customer → denied. Admin without a capability → denied. Unknown handler → denied.
- Round-robin: sequential starts distribute evenly; `asyncio.gather` of 20 starts → distribution within ±1 and no duplicates/errors;
  inactive seller skipped; single owner → everything to the owner; new seller doesn't reassign existing customers.
