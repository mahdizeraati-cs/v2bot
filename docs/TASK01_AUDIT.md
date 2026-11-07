# TASK01_AUDIT — Cross-check of Task 01 (panel adapters) against the codebase

**Mode:** read-only. Only this file was created; nothing else was modified.
**Scope:** `v2bot/` working tree (branch `main`, up to date with `origin/main`).
**Reference:** `docs/agent-tasks/01-panel-adapters.md` (acceptance criteria), `AGENTS.md`, skills `panel-adapters` + `safe-change-workflow`.

> Note: the "previous report" file itself was not provided in this thread, so I cannot diff its file table directly. Section 1 below records the **observed ground truth** from `git status`, `git diff --stat`, and `git ls-files` so you can compare it against the report you have.

---

## خلاصه / Summary

Task 01's adapter layer exists in the working tree and its tests pass (`48 passed, 1 skipped`), but the work is **entirely untracked (not committed)** and the adapters are **not yet wired into the bot handlers**. Every panel call site in `bot/handlers/admin_handlers.py` and `bot/handlers/user_handlers.py` still calls the legacy `core/services/panel_client.py::MarzbanClient` directly. Several acceptance criteria are only partially met or not met at all (see section 3).

---

## فایل‌های تغییرکرده / Files changed

### Git ground truth

`git status` (working tree, branch `main`):

```
Changes not staged for commit:
  modified:   core/database/models.py
Untracked files:
  .agents/
  AGENTS.md
  core/database/migrations/versions/c05b38e09193_add_panel_type_and_config_to_servers.py
  core/panels/
  docs/
  pyproject.toml
  requirements-dev.txt
  tests/
  user-settings.snippet.jsonc
```

`git diff --stat`:
```
 core/database/models.py | 5 +++++
```

### Specific files asked about

| File | Status | Evidence |
|---|---|---|
| `requirements.txt` | tracked, present | `git ls-files` lists it; not in modified/untracked |
| `requirements-dev.txt` | **untracked (new)** | appears in `git status` untracked list |
| `docker-compose.yml` | tracked, present | `git ls-files` lists it; unchanged |
| `.env*` / `.env.example` | **NOT FOUND** | `git ls-files --others --exclude-standard | grep -i env` → no matches; `find_path .env*` → no matches |
| `alembic env.py` | tracked, present | `core/database/migrations/env.py` listed by `git ls-files` (unchanged) |
| `core/database/models.py` | tracked, **modified** (+5 lines: `panel_type`, `panel_config`) | `git diff core/database/models.py` |

`core/panels/` (8 files, all new/untracked): `__init__.py`, `base.py`, `common.py`, `factory.py`, `groups.py`, `http.py`, `token_base.py`, `pasarguard.py`, `marzban.py`, `hiddify.py`.

Migration `c05b38e09193_add_panel_type_and_config_to_servers.py` is untracked/new; its `down_revision` is `78aefc94582e`, and `versions/78aefc94582e_init_database.py` exists (down-revision present).

---

## docs/panels.md — existence and VERIFY table

**`docs/panels.md` EXISTS** at `v2bot/docs/panels.md`.

Caveat: its header says "Status: draft from research; no code changed yet" and section 0 claims `core/services/panel_client.py::MarzbanClient` is the only client — but `core/panels/` already exists, so that section is stale relative to the code (observation only, no change made).

### VERIFY table (every item in `references/*.md`, resolved via `docs/panels.md`)

Legend: **confirmed** = read in the panel's own source/docs; **contradicted** = source disagrees with the reference note; **unreachable/unresolved** = could not be confirmed from a reachable official source.

| Panel | VERIFY item | Result | Source |
|---|---|---|---|
| PasarGuard | token endpoint/format | confirmed | `PasarGuard/panel` `app/routers/admin.py::admin_token` (`POST /api/admin/token`, form, `access_token`) |
| PasarGuard | `expire` format | confirmed (type) | `app/models/user.py` (`datetime \| int \| None`); bot sends numeric string, keep byte-for-byte |
| PasarGuard | status values / disable | confirmed | docs groups page; `active`/`disabled`/`on_hold`, dedicated `PUT …/disabled` |
| PasarGuard | `GET /api/groups` envelope & fields | confirmed | `GroupsResponse`/`GroupResponse` (`id`, `name`, `inbound_tags`, `is_disabled`, `total_users`) |
| PasarGuard | `subscription_url` absolute? | **unresolved** | plain string, generated in operation/subscription layer not fetched; adapter normalises |
| PasarGuard | username rules | confirmed | `UserValidator.validate_username` (3–128, `[a-zA-Z0-9-_@.]`) |
| PasarGuard | restricted admins (`allowed_group_ids`) | confirmed | `app/operation/permissions.py` |
| Marzban | `GET /api/inbounds` shape | confirmed | `Gozargah/Marzban` `app/routers/system.py` (`Dict[ProxyTypes, List[ProxyInbound]]`) |
| Marzban | omitted `inbounds` = all | confirmed | `UserCreate.validate_inbounds` (adapter still sends explicitly) |
| Marzban | username rules | confirmed | `app/models/user.py` regex `^(?=\w{3,32}\b)[a-zA-Z0-9-_@.]+…` (3–32) |
| Marzban | `subscription_url` absolute/relative | confirmed possible relative | built from `XRAY_SUBSCRIPTION_URL_PREFIX`/path; empty prefix ⇒ relative |
| Marzban | status values | confirmed | create `active`/`on_hold`; modify `active`/`disabled`/`on_hold`; read adds `limited`/`expired` |
| Marzban | extend semantics | **unresolved** | no API rule; adapter rule unit-tested, live-check needed |
| Marzban | `/docs` path | **unresolved** | FastAPI default, not verified on a real panel |
| Hiddify | v2 user endpoints | confirmed | `hiddify/hiddifypanel` `restapi/v2/admin/user_api.py`, `users_api.py`, `schema.py` |
| Hiddify | header auth (`Hiddify-API-Key`) | confirmed | `auth.py` (`auth_before_request`, admin under admin proxy path) |
| Hiddify | field names / GB float units | confirmed | `UserSchema` (`usage_limit_GB`, `package_days`) |
| Hiddify | `mode` values | **unresolved** | `UserMode` enum not fetched; third-party clients report `no_reset\|daily\|weekly\|monthly` |
| Hiddify | subscription URL | **contradicted / unresolved** | reference expected it in response; schema has none → composed `https://<domain>/<client_proxy_path>/<uuid>/`, exact shape unresolved, `panel_config.sub_url_template` + owner confirmation |
| Hiddify | extend via `package_days`/`start_date` | **unresolved** | `PatchUserSchema` accepts both; open issue hiddify/Hiddify-Manager#5246; rule to live-test |
| Hiddify | disable/enable | confirmed | `enable` flag in `PatchUserSchema` |
| Hiddify | groups/inbounds | confirmed none | `supports_targets = False` |
| Hiddify | ping endpoint | confirmed (version-dependent) | how-to says `/panel/version`; source registers `/ping/` and `/info/`; adapter tries `ping/` then falls back to `info/` |

---

## Acceptance criteria of Task 01 — one-by-one evaluation

| # | Acceptance criterion (from `docs/agent-tasks/01-panel-adapters.md`) | Verdict | Evidence / command |
|---|---|---|---|
| 1 | Contract tests pass for all three adapters with mocked HTTP (create/get/extend/disable/enable/delete, 401→re-auth, timeout, 4xx) | ✅ | `tests/test_adapter_contract.py` parametrized over `pasarguard`/`marzban`/`hiddify`: `test_full_lifecycle`, `test_wrong_credentials_raise_auth_error`, `test_timeout_maps_to_unreachable_and_no_secret_in_logs`, `test_4xx_maps_to_rejected`, `test_retry_after_timeout_does_not_duplicate`, `test_reauth_once_after_401` (skipped for hiddify — expected, §4h). `venv/bin/python -m pytest -q` → `48 passed, 1 skipped`. |
| 2 | PasarGuard create-user payload identical to pre-refactor payload except `group_ids` | ✅ (with caveat §4a) | `tests/test_pasarguard.py::test_create_payload_identical_to_legacy_except_group_ids` compares to `_legacy_payload()` (hardcoded dict, not legacy-code execution). |
| 3 | Group resolution: all / selected / renumbered / id-reused / empty / disabled group excluded | ⚠️ PARTIAL | `tests/test_pasarguard.py`: `test_all_enabled_groups_are_used_and_disabled_excluded`, `test_ids_come_from_live_listing_not_from_code`, `test_no_enabled_group_fails_cleanly`, `test_empty_listing_fails_cleanly`, `test_listing_falls_back_to_simple_when_groups_read_is_denied`. **"selected" mode, renumbered/id-reused handling, and admin alert NOT implemented** — `core/panels/groups.py` docstring: "حالت انتخابی وجود ندارد" (no selective mode); owner decision recorded in code. |
| 4 | Registering a Marzban and a Hiddify server end-to-end in a handler-level test; wrong password and unreachable host show distinct Persian messages; secrets never in logs | ❌ NOT MET | No handler-level registration test exists; no panel-type-aware registration FSM in `bot/handlers/admin_handlers.py` (only `_test_marzban_connection`, MarzbanClient-only, L917-927). Wrong password → `PanelAuthError` → Persian via `core/panels/base.py::error_message_fa` ✅ (adapter level). Unreachable → `PanelUnreachable` → Persian ✅. Secrets never in logs ✅ (§4c). |
| 5 | Alembic upgrade/downgrade round-trip passes; existing rows get `panel_type='pasarguard'` | ⚠️ NOT RUN LOCALLY | Migration `c05b38e09193`: `panel_type` `server_default='pasarguard'`, `nullable=False` (L24); model `core/database/models.py:77` `server_default="pasarguard"` → existing rows get `'pasarguard'` by server default. `down_revision = '78aefc94582e'` present. Downgrade drops both columns (destructive, §4b). Round-trip **not executed**: no local Postgres (127.0.0.1:5433 and :5432 closed), `DATABASE_URL` unset. |
| 6 | `ruff` and `pytest` pass | ✅ | `venv/bin/python -m ruff check .` → `All checks passed!`; `venv/bin/python -m ruff format --check .` → `31 files already formatted`; `venv/bin/python -m pytest -q` → `48 passed, 1 skipped in 3.38s`. |

---

## Specific audits

### 4a) PasarGuard payload equality — legacy code execution or hardcoded dict?

**Hardcoded/handwritten dict — NOT legacy code execution.**

`tests/test_pasarguard.py:13-30` defines `_legacy_payload(group_ids)` as a literal dict and `test_create_payload_identical_to_legacy_except_group_ids` (L33-37) asserts `sent == _legacy_payload([3, 7])` plus key order. The legacy code `core/services/panel_client.py::MarzbanClient.create_user` still exists but is **not imported or executed by any test**. The ground truth was recorded in `docs/panels.md` §0 ("Exact create-user request the bot sends today").

### 4b) Migration — DB-level `server_default` on `panel_type`? Does downgrade work?

- **DB-level `server_default`: YES.** `core/database/models.py:77`: `panel_type: Mapped[str] = mapped_column(String(16), default="pasarguard", server_default="pasarguard")`. Migration `core/database/migrations/versions/c05b38e09193_add_panel_type_and_config_to_servers.py:24`: `op.add_column('servers', sa.Column('panel_type', sa.String(length=16), server_default='pasarguard', nullable=False))`. `panel_config` is `JSONB, nullable=True` (models.py:79, migration:25).
- **Downgrade:** migration L29-33 drops `panel_config` then `panel_type`. Structurally valid and runs without error, but **destructive** — `panel_config` data is lost and there is no data preservation/restoration. `down_revision = '78aefc94582e'` exists (`versions/78aefc94582e_init_database.py`). Round-trip not executed locally (§3, AC5).

### 4c) Secrets leaked in logs across `core/panels`?

**No.** Grep for `logger.(debug\|info\|warning\|error\|exception)` containing `token\|password\|api_key\|subscription_url\|secret` across `core/panels/*.py` → no matches.

Only two `logger.warning` calls exist:
- `core/panels/groups.py:45-46`: logs target-set change **counts only** (`len(previous)`, `len(current)`), no IDs/secrets.
- `core/panels/http.py:116-119`: logs only `type(exc).__name__`; comment explicitly notes the URL may contain the Hiddify admin path and is deliberately excluded.

Corroborated by `tests/test_adapter_contract.py::test_timeout_maps_to_unreachable_and_no_secret_in_logs` (asserts each secret in `tests/conftest.py:21` `SECRETS = ("pw", "KEY")` is absent from `caplog.text`).

### 4d) Token cache per-server and lock per-server, or global?

**Per-server, keyed by `cache_key`** — the dicts are module-level but entries are per-server, not one global token.

- `core/panels/token_base.py:16-17`: `_TOKEN_CACHE: dict[str, tuple[str, float]] = {}`, `_LOCKS: dict[str, asyncio.Lock()] = {}` (module scope).
- `core/panels/factory.py:23`: `cache_key = f"srv:{server_id}" if server_id else f"tmp:{server.panel_url}|{server.username}"` — per server.
- `core/panels/token_base.py:42`: `self.cache_key = cache_key or f"{self.base_url}|{username}"`.
- `core/panels/token_base.py:50`: `lock = _LOCKS.setdefault(self.cache_key, asyncio.Lock())` — per-server lock.
- `core/panels/token_base.py:52-64`: cache read/write keyed by `self.cache_key`.

So: **per-server keyed cache + per-server keyed lock** (not a single global token/lock). `clear_token_cache()` (token_base.py:20-22) clears both globally, used in tests (`tests/conftest.py:26`).

### 4e) Is `verify_ssl` read from `panel_config`?

**YES.** `core/panels/factory.py:20-21`:
```python
config = dict(getattr(server, "panel_config", None) or {})
verify_ssl = config.get("verify_ssl", True) is not False
```
Default `True` (TLS on unless explicitly `false`), passed to `PanelHTTP` (token_base.py:44 / hiddify.py:65-67). Verified by `tests/test_marzban_hiddify.py::test_factory_honours_verify_ssl_flag_per_server` (L136-148): `panel_config={"verify_ssl": False}` → `http.verify_ssl is False`; `{}` → `True`.

### 4f) `resolve_group_ids` with an empty list — raises `PanelConfigError` and triggers an admin alert?

- **Raises `PanelConfigError`: YES.** `core/panels/groups.py:51-56`: `resolve_group_ids` raises `PanelConfigError("هیچ گروه فعالی در پنل پیدا نشد…")` when no enabled IDs. Covered by `tests/test_pasarguard.py::test_no_enabled_group_fails_cleanly` and `::test_empty_listing_fails_cleanly`.
- **Triggers an admin alert: NO.** There is **no alerting at all** in `core/panels/groups.py` — no `alert_server_admins_if` or admin-notification function exists anywhere in `core/panels` (grep for `alert\|admin_alert\|notify_admin` in `core/panels/*.py` → no matches). The "selected" mode with `alert_server_admins_if(problems)` from the skill was **not implemented** (owner decision: all-mode only, recorded in `groups.py` docstring). So an empty/disabled group list fails cleanly but does **not** alert an admin.

### 4g) Hiddify — official source for each HTTP endpoint/method (incl. PATCH) and subscription link format?

- **Endpoints/methods (incl. PATCH):** official panel repo `hiddify/hiddifypanel` (`auth.py`, `restapi/v2/admin/user_api.py`, `users_api.py`, `schema.py`, `panel/__init__.py`, `panel/info.py`) plus official API how-to https://hiddify.com/manager/contribution/How-to-use-API-in-HiddifyManager-project. `PATCH` confirmed from source (`docs/panels.md` §3: "update | **PATCH** `/admin/user/{uuid}/` | not PUT"); implemented in `core/panels/hiddify.py::extend_user` (L167) and `::set_enabled` (L171-172). `ping`: how-to says `/panel/version`, but source registers `/ping/` and `/info/` → version-dependent; adapter tries `ping/` then falls back to `info/` (`hiddify.py:99-106`).
- **Subscription link format:** **NOT verified from an official source.** `docs/panels.md` §3 VERIFY marks it **contradicted / unresolved**: the `UserSchema` has no subscription URL, so it is composed as `https://<domain>/<client_proxy_path>/<uuid>/` (`core/panels/hiddify.py:198-207`, `DEFAULT_SUB_TEMPLATE` at L31), overridable via `panel_config.sub_url_template`, and requires owner confirmation. The panel's built-in Swagger (per-install authority) was not reachable.

### 4h) Exact reason for 1 skipped in the test suite?

`tests/test_adapter_contract.py:92-94`, `test_reauth_once_after_401`:
```python
if panel.kind == "hiddify":
    pytest.skip("Hiddify توکن ندارد (کلید ثابت در هدر)")
```
Hiddify uses a static API key in the `Hiddify-API-Key` header (no bearer token, no re-login on 401), so the reauth-after-401 test does not apply. This is the **only** skip; `48 passed, 1 skipped`.

### 4i) All remaining references to `MarzbanClient` (scripts, tests, dynamic imports)?

`MarzbanClient` is **not removed** and is still actively imported by all four handler call sites:

| File | Location | What |
|---|---|---|
| `bot/handlers/admin_handlers.py` | L40-44 | `from core.services.panel_client import MarzbanClient` |
| `bot/handlers/admin_handlers.py` | L462-466 | `admin_approve_transaction` constructs `MarzbanClient(...)` |
| `bot/handlers/admin_handlers.py` | L917-927 | `_test_marzban_connection` constructs `MarzbanClient(...)` + `client.login()` |
| `bot/handlers/admin_handlers.py` | L2942-2946 | `admin_customer_service_monitor` constructs `MarzbanClient(...)` |
| `bot/handlers/user_handlers.py` | L32-36 | `from core.services.panel_client import MarzbanClient` |
| `bot/handlers/user_handlers.py` | L760-764 | `process_wallet_buy` constructs `MarzbanClient(...)` |
| `bot/handlers/user_handlers.py` | L1336-1340 | `process_service_monitoring` constructs `MarzbanClient(...)` |
| `bot/handlers/user_handlers.py` | L1707-1711 | `free_test_generate` constructs `MarzbanClient(...)` |
| `core/services/panel_client.py` | L9-19 | `class MarzbanClient` definition (legacy client still present) |
| `core/panels/pasarguard.py` | L68 | comment: "عیناً مثل MarzbanClient.create_user قدیمی است" |
| `docs/ARCHITECTURE_NOTES.md` | L18-22, L109-113 | module map + panel layer reference `core/services/panel_client.py::MarzbanClient` |
| `docs/panels.md` | L10-13, L14-15, L155-156 | section 0 + cross-panel contract decisions |
| `tests/test_pasarguard.py` | L14 | `_legacy_payload` docstring: "عین payload کدِ قبلی (MarzbanClient.create_user + handlerها)" |

**Conclusion:** the new `core/panels/` adapters are **not wired into any handler**; every create/renew/disable/usage call site still uses the legacy `MarzbanClient`. No dynamic imports of `MarzbanClient` were found (only direct imports).

---

## کارهای باقی‌مانده / سوالات (remaining work & questions)

1. Wire `get_adapter(server)` into the four handler call sites (and remove/replace `MarzbanClient` usage) — currently all panel writes still go through the legacy client.
2. Implement the panel-type-aware registration/edit FSM flow (ask type first → `credential_schema()` → `ping()` → discovery → confirm) and a handler-level test for Marzban + Hiddify registration (AC4).
3. Decide whether to implement `group_mode="selected"` + renumbered/id-reused handling + admin alert in `resolve_group_ids` (currently all-mode only per owner decision in `groups.py` docstring).
4. Run the Alembic upgrade/downgrade round-trip on a local Postgres (`docker compose up -d db`, port 5433) with a throwaway DB and `DATABASE_URL` pointing at localhost — not possible here (no local Postgres running, `DATABASE_URL` unset).
5. Confirm Hiddify subscription URL format and `mode` values against a real panel / its Swagger (currently unresolved).
6. Add `.env.example` (no `.env*` files exist at all) if any new env vars are introduced.

---

## مشاهدات خارج از محدوده (بدون تغییر)

- `docs/panels.md` section 0 is stale (claims `MarzbanClient` is the only client and "no code changed yet", but `core/panels/` exists).
- `docs/ARCHITECTURE_NOTES.md` still describes the pre-Task-01 state (only `MarzbanClient`, no `panel_type` column).
- `core/services/panel_client.py::MarzbanClient` remains in place and in use by handlers (intended per Task 01 plan: "the old client is kept until all call sites move").
- `reset_db.py`, `reset_alembic.py`, `res_db.py`, `restore_backup.sh` exist in the repo root but were **not** run or touched (hard prohibition respected).

---

## نحوه تست (دستورات + خروجی)

Run from `v2bot/` with the venv interpreter:

```
venv/bin/python -m pytest -q
# 48 passed, 1 skipped in 3.38s

venv/bin/python -m ruff check .
# All checks passed!

venv/bin/python -m ruff format --check .
# 31 files already formatted
```

Alembic round-trip (`alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head`, then `alembic check`) was **not executed** — no local Postgres is reachable (127.0.0.1:5433 and :5432 closed) and `DATABASE_URL` is not set; connecting to a non-local DB is prohibited by `safe-change-workflow`.
