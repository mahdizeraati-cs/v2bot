# AGENTS.md — v2bot

Telegram store bot for V2Ray subscriptions. Python, aiogram 3, async SQLAlchemy + asyncpg, PostgreSQL, Alembic, APScheduler, aiohttp.
Entry: `main.py`. Handlers: `bot/handlers/{admin,user}_handlers.py`. Models: `core/database/models.py`
(`Server`: vendor_id, is_shared, name, panel_url, username, password, panel_type, panel_config).
Panel layer: `core/panels/` (adapters, use `get_adapter(server)`). Legacy client `core/services/panel_client.py` (`MarzbanClient`) is KEPT whole, including methods with no callers.

## Style (always on)
Talk caveman, level full (skill `caveman` if loaded; these rules apply even if it is not):
drop articles, filler, pleasantries, hedging. Fragments OK. Short.
Keep exact and normal: code, commands, file contents, commit messages, error text, tool output.
Questions to owner and warnings about data loss or security: clear normal sentences.
English only. Never write Persian in Latin letters. "stop caveman" = normal mode.

## How to work
- Task files in `docs/agent-tasks/` are the source of truth. Follow their phases and STOP gates. One task per thread.
  Inside the implementation phase: one function per step. After each step run
  `python -m ruff check bot core --select F,E9` and `python -m pytest -q`, show the real summary lines, then stop and wait for my "next".
- Decisions live in `docs/DECISIONS.md`. You write them. I approve first:
  - A task phase surfaces a choice, or I state a rule: propose the exact line (one line, dated, with your default). Wait for my OK.
  - Only after my OK, append it at the bottom as `- [ ] YYYY-MM-DD: text`. Never write a decision I did not approve.
  - Right after you finish and verify the work behind a decision (ruff + pytest green), tick it `[x]` and append `(done YYYY-MM-DD: test name)`.
  - Never tick early. Never delete or reorder lines. `[~]` = superseded; propose that edit first, wait for OK.
- Act with tools. Max 5 lines of plan before the first tool call. Never restate a plan you already wrote.
- Read only: files named in the prompt, the task file, `docs/DECISIONS.md`, and the code you edit. Do not open other docs or skills (caveman is the only skill in use).
- Tool call fails twice: stop, show error. Never loop.
- Never claim success without command output.

## Hard rules
- Treat `DATABASE_URL` as production. Never run anything that connects to a database (no alembic, no scripts).
  Tests use the fake panels in `tests/`. Need a migration: write the file, tell me to run it.
- Never run `reset_db.py`, `reset_alembic.py`, `res_db.py`, `restore_backup.sh`. Never read or edit `.env` (you may edit `.env.example`). Never `git push`. Do not `git commit`; I do.
- New env var: add its name to `.env.example`, no values.
- No new dependencies. No edits outside the current step.
- Never delete existing code, even if unused (future buttons may use it). Unused import left after a switch: keep it, add `# noqa: F401`.
- Money: integers, never float. Status changes: conditional UPDATE or SELECT ... FOR UPDATE. Never hold a DB transaction during a panel call.
- Panels only through `get_adapter(server)`. New adapter call must send the same panel request as the old `MarzbanClient` call (prove with a fake-panel test). No secrets, tokens or subscription links in logs. Escape user text in HTML messages.
- Every admin callback: authorize server-side, check target object belongs to actor.
- Blocked: ask one short question, propose a default.
