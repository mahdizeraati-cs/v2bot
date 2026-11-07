# Task 01 — Panel adapters (PasarGuard · Marzban · Hiddify) + dynamic groups + typed server registration

**Read first:** `AGENTS.md`, skill `panel-adapters` (and its `references/*`), skill `safe-change-workflow`, `docs/ARCHITECTURE_NOTES.md` (if Task 00 was done).

## Context (from the owner)
1. The web-service layer supports only PasarGuard. Add Marzban and Hiddify, **based on each panel's official API documentation**.
2. PasarGuard user creation sends `group_ids` as a **hard-coded numeric array**. A provider changed the numbers and one server broke.
   Instead, read the groups each panel actually has, and send them all.
3. In the admin flow «ثبت سرور», ask **what type of panel it is** and collect the fields that type's API needs.

## Goal
A pluggable `PanelAdapter` layer used by every call site; PasarGuard behaviour preserved; Marzban + Hiddify supported;
group IDs resolved live; server registration/edit flow aware of panel type.

## Phase 1 — Research (read-only)
1. Locate the current panel layer and every call site (create / renew / disable / delete / usage-sync / registration).
2. Fetch official sources from `references/*.md` and create `docs/panels.md`: per panel → auth, endpoints you will use, request payload, a sample response, source URL, and a **VERIFY-resolved** table (each VERIFY item from the references: confirmed / contradicted / unreachable).
3. Record the exact payload the current PasarGuard code sends (it is the ground truth to preserve).
If an official source is unreachable, say which one and continue with the others; do not invent endpoints.

## Phase 2 — Plan and gate
Write a ≤ 1-page plan: module layout, `PanelType`/`panel_config` migration, call-site changes (list files), registration FSM states, risks, rollback.
Ask your open questions in one batch (Persian), each with a proposed default. Likely ones:
- `group_mode` default `all` for existing PasarGuard servers → users on existing servers will now receive **all enabled groups**, not the old hard-coded subset. OK? (owner asked for "send all"; confirm.)
- Should registration refuse to save a server when `ping()` fails, or allow saving with a warning?
- Hiddify: which proxy paths does the owner use (admin path, client path)? Same domain for subscription links?

`⛔ منتظر تایید شما هستم` — no file-modifying tool calls until the owner approves.

## Phase 3 — Implement (order matters; run verification after each step)
1. **Contract + errors + factory + migration** (`servers.panel_type` default `pasarguard`, `servers.panel_config JSONB`). Round-trip the migration locally.
2. **`PasarGuardAdapter`** — move existing behaviour behind the adapter, switch all call sites to `get_adapter(server)`. No behaviour change yet. Tests prove payload equality.
3. **Dynamic groups** — `list_targets()` + `resolve_group_ids()` exactly as in the skill (cache, renumbered vs id-reused handling, never create a user with zero groups, alert on drift). Remove the hard-coded array.
4. **Registration/edit flow** — type first → fields from `credential_schema()` → delete secret messages → `ping()` → discovery → confirm. Edit screen: type, test connection, refresh groups/inbounds, group mode. Legacy servers appear as PasarGuard.
5. **`MarzbanAdapter`** (inbounds discovery, explicit `proxies`/`inbounds`).
6. **`HiddifyAdapter`** (API-key header, GB units, `package_days` semantics, configurable subscription URL).
7. **Docs** — finalise `docs/panels.md`; `.env.example` if needed.

## Constraints
- No new runtime dependency unless unavoidable (justify). No third-party panel SDKs. Reuse the existing HTTP client.
- Existing servers, orders and subscriptions keep working after the migration without manual steps.
- No secrets, tokens or full subscription URLs in logs. TLS verification on unless `panel_config.verify_ssl` is explicitly false.
- Do not touch receipts/RBAC code in this task.

## Acceptance criteria (each must be proven by a test or command output)
- [ ] Contract tests pass for all three adapters with mocked HTTP (create/get/extend/disable/enable/delete, 401→re-auth, timeout, 4xx).
- [ ] PasarGuard create-user payload is identical to the pre-refactor payload except `group_ids`.
- [ ] Group resolution: all / selected / renumbered (follows name) / id-reused (rejected + alert) / empty (clean failure) / disabled group excluded.
- [ ] Registering a Marzban and a Hiddify server works end-to-end in a handler-level test; wrong password and unreachable host show distinct Persian messages; secrets never appear in logs.
- [ ] Alembic upgrade/downgrade round-trip passes; existing rows get `panel_type='pasarguard'`.
- [ ] `ruff` and `pytest` pass.

## Before you answer, self-check
Did I verify each endpoint against an official source? Did I keep the old PasarGuard payload? Is any panel call inside a DB transaction? Does any log line contain a secret?

Final report: use the template in `AGENTS.md` §6; list every VERIFY item and its resolution.
