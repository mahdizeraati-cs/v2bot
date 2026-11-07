# Task 00 — Discovery (READ-ONLY)

**Mode:** read-only. The only file you may create is `docs/ARCHITECTURE_NOTES.md`. No other edits, no migrations, no DB connections.

## Why
`AGENTS.md` only knows the repo root. Tasks 01 (panel adapters), 02 (receipts + auto-approve) and 03 (RBAC/broadcast/forced join)
need facts about `bot/` and `core/`. Wrong assumptions here would turn into wrong migrations later, so this task builds a cited map first.

## Rules for this task
- Every statement cites `path::symbol` (class/function) or `path:line`. If you cannot find it: write `NOT FOUND`. Do not infer.
- Quote nothing long; summarise. Secrets/values from `.env` are out of scope.
- If something contradicts `AGENTS.md` §1, list it under "Contradictions".

## Steps
1. List the tree (2 levels deep), entry points, routers, middlewares, services/utils, models, Alembic location, scheduler jobs.
2. Read in this order: `main.py` → `bot/middlewares/*` → `bot/handlers/*` → `core/database/models/*` → `core/utils/*` → Alembic `env.py` + latest revisions.
3. Fill the template below. Prefer tables.
4. Re-read your notes once and delete anything you could not cite.

## Template — `docs/ARCHITECTURE_NOTES.md`
**A. Module map** — one line per important module: purpose, main functions.
**B. Database** — tables, columns (type, nullability), FKs, enums, money/amount type and unit, indexes. Where are Alembic revisions and does `env.py` normalise the URL like `main.py`?
**C. Identity and roles** — how owner / admin / seller / customer are identified (`OWNER_ID`, tables/columns). Where is a customer assigned to a seller/admin? Describe the round-robin: function, where the cursor lives, what happens with one seller, new seller, disabled seller.
**D. Handler inventory** — table: `file::function | trigger (command/callback/FSM state) | filters/role check | data scope`. Include *every* admin-facing handler.
**E. Panel layer** — functions that call panels, endpoints used, payload shape, auth method, **exact place(s) where `group_ids` is hard-coded**, `servers` table fields, how an admin registers/edits a server today (FSM states), where subscriptions are created / renewed / disabled / deleted / synced.
**F. Payments and receipts** — customer flow from plan selection to delivery; where the receipt photo is received, forwarded, and **deleted**; who reviews (which admin/seller/owner and why); order/payment tables and statuses; wallet (if any).
**G. Settings** — where bot/admin settings are stored (table/columns/key-value), how the admin settings screen is built.
**H. Broadcast and forced join** — implementation, recipient query (paste the filter condition, not the whole file), where channels are stored, where membership is checked.
**I. Scheduler jobs and Redis usage.**
**J. FSM** — storage backend actually used (memory/Redis), list of StatesGroups.
**K. Contradictions with AGENTS.md.**
**L. Top-10 risks for tasks 01–03**, ranked, each with the file::symbol that causes it.

## Final message (Persian, ≤ 15 lines)
What you found in one paragraph per task (01 / 02 / 03), then at most 5 questions you could not answer from the code.
