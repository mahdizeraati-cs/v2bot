---
name: safe-change-workflow
description: Safe-change checklist for this repo — Alembic migrations (additive, reversible, local DB only), the local verification routine (ruff, pytest, migration round-trip), and the final report format. Use this skill before creating or editing any migration or DB model, before running any command that opens a database connection, and at the end of every task to verify and report — even for "small" changes, because a bad migration or a command run against the Railway database is the most expensive mistake available here.
---

# Safe change workflow

## 0. Local-DB guard (before ANY command that connects to a database)
1. Find the target: read the variable *name* and the **host** part of `DATABASE_URL` from the environment/config without printing the password.
2. Proceed only if the host is `localhost`, `127.0.0.1` or the compose service `db`. Otherwise stop and tell the owner — the repo is deployed on Railway and `.env` may point at production.
3. Local DB: `docker compose up -d db` (Postgres 15, host port 5433). Use a throwaway DB name for experiments.
4. Alembic's `env.py` and `main.py` must resolve the URL the same way (the `postgresql://` → `postgresql+asyncpg://` rewrite). If they differ, report it; fix it through a shared helper only when the task asks.

## 1. Migrations
- Autogenerate to a draft, then **read and edit** it. Autogenerate misses enum changes, renames (shows drop+add), server defaults and data backfills.
- Additive first. New NOT NULL column on a populated table = add with `server_default` (or nullable) → backfill → (later revision) tighten.
- Prefer `String` + `CHECK` over native PG enums for statuses that will grow; if you use a native enum, remember `ALTER TYPE … ADD VALUE` limits inside transactions.
- Every revision has a working `downgrade()`, an explicit short name, and touches one concern.
- Never edit a revision that has been applied anywhere; add a new one.
- Backfill with SQL (`op.execute`) — no ORM models imported inside migrations.
- Round-trip on an empty local DB: `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head`; then `alembic check` (no pending autogenerate diff).
- Large/risky data changes: write the SQL, print what it would affect (`SELECT count(*)`), and ask the owner before running it anywhere non-local.

## 2. Verification routine (run after each slice, report the output)
```
ruff check .
ruff format --check .
pytest -q
```
If `ruff`/`pytest` are not configured yet, add minimal config (`pyproject.toml`) as a separate, small change and say so. Tests must not need the network or real credentials.
If something cannot be run in this environment, write exactly what and why — never write "should pass".

## 3. Change hygiene
- Keep diffs small and focused; do not reformat unrelated files.
- New env var → `.env.example` + README mention. New dependency → justification + pinned version.
- Leave changes uncommitted unless asked; propose a Conventional Commits message per logical slice.

## 4. Final report
Use the template from `AGENTS.md` §6. Always include: which acceptance criteria are proven by which test/command, what you did *not* verify, and
any observations outside scope (do not fix them silently).
