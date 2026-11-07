# Task 03 — Access control audit, owner-wide broadcast, forced join, round-robin check

**Read first:** `AGENTS.md`, skill `rbac-tenancy` (follow its audit procedure and fixture), skill `safe-change-workflow`, `docs/ARCHITECTURE_NOTES.md` (sections C, D, H).

## Context (from the owner)
- Owner access control is wrong/limited. Example: the owner's **broadcast** does not reach everyone.
- Customers are attached to sellers/admins by **round-robin**; if the owner is the only seller, all customers attach to the owner. **Verify this is correct and safe.**
- A broadcast or a **forced-join channel** set by the owner must apply to **all customers of all sellers and admins below them**. Today it does not.
- Audit the rest of the permission model yourself, tell the owner what you found, ask how it should work, and then implement exactly what the owner decides.

## Phase 1 — Audit (read-only) → `docs/rbac_audit.md`
Follow the audit procedure in the skill. Required content:
1. Role map. 2. Handler inventory table (every admin/owner handler; use the example row format from the skill).
3. Round-robin review with the six scenarios listed in the skill.
4. Root cause of the broadcast bug and the forced-join bug (name the exact filter/query/middleware).
5. Findings ranked: privilege escalation / IDOR → data leak → wrong behaviour → cosmetic.
6. Proposed permission matrix with a default in every cell.

## Phase 2 — Ask the owner and gate
Send a short Persian summary of the findings (top 5) and ask, in one numbered batch with your proposed default each:
1. نقش «ادمین» دقیقاً چه فرقی با «فروشنده» دارد؟ (می‌تواند سرور/پلن بسازد؟ مشتری دارد؟ فقط فیش تایید می‌کند؟)
2. هر ردیفِ `?` در ماتریس دسترسی (سرورها، پلن‌ها، فیش‌ها، آمار مالی، پیام همگانی ادمین…) چطور باشد؟
3. پیام همگانی مالک: فقط مشتری‌ها یا فروشنده‌ها و ادمین‌ها هم دریافت کنند؟
4. وقتی چند فروشنده هست، مالک هم در چرخه‌ی round-robin بماند یا فقط فروشنده‌ها؟
5. اگر فروشنده غیرفعال/حذف شد، مشتری‌هایش به بقیه منتقل شوند یا بمانند؟
6. جوین اجباری: اگر ربات در کانال ادمین نبود، کاربران عبور کنند (پیشنهاد من) یا مسدود بمانند؟

`⛔ منتظر تایید شما هستم`. Record answers in `docs/DECISIONS.md`. Implement nothing before they are recorded.

## Phase 3 — Implement exactly the decisions
1. `Role` enum, `require_role` filter, **default-deny** on all admin handlers; fix every privilege-escalation/IDOR finding first.
2. Single scoping helper (`customers_visible_to(actor)` or equivalent) used by every list/lookup; remove hand-written seller filters.
3. Broadcast: recipients from the helper (+ staff if decided), unique chat IDs, background task, ≤ 25 msg/s, `RetryAfter`/`Forbidden` handling, progress + final stats to the sender.
4. Forced join: effective channels = owner-level ∪ seller-level, enforced in one middleware before all customer routers, short-TTL cache, fail-open + alert per decision, «✅ عضو شدم» re-check.
5. Round-robin: fix whatever the audit found (cursor in DB, atomic advance, skip inactive, sticky assignment).
6. Tests with the fixture from the skill (O, S1, S2, A1, C1…C6) including the concurrency test.

## Constraints
- Schema changes only via Alembic and only if the decisions require them (e.g. channel scope column, cursor row). Backfill existing rows safely.
- Do not change unrelated business logic. Behaviour changes that the audit reveals but the owner did not decide go in "observations".
- No secrets in logs; user-supplied text is HTML-escaped in broadcasts to staff.

## Acceptance criteria
- [ ] Owner broadcast reaches every customer under every seller/admin (fixture test) and respects the decision about staff.
- [ ] Seller broadcast reaches only their customers.
- [ ] Owner forced channel applies to all customers; seller channel only to theirs; union enforced by one middleware; misconfigured channel does not lock customers out.
- [ ] Crafted callbacks against other sellers' objects are denied (tests for at least: ban/unban, balance change, payment view, customer detail).
- [ ] Every admin handler has an explicit role declaration (test iterates over routers and fails on an undeclared handler).
- [ ] Round-robin: even distribution, concurrent starts safe, single-owner case correct, inactive seller skipped, no reassignment of existing customers.
- [ ] Migration round-trip (if any), `ruff`, `pytest` OK.

## Self-check before answering
Can any non-owner reach an owner-only action by editing `callback_data`? Does any recipient/channel query still filter by only the actor's own ID? Is the round-robin cursor in process memory anywhere?

Final report: `AGENTS.md` §6, plus the final permission matrix as implemented.
