# Panel integration notes (Task 01 — Phase 1 research)

Status: **draft from research; no code changed yet.** Each fact is tagged with its source.
Sources were fetched on 2026-11-06 from the official GitHub repositories (raw files) and official docs.

Legend for the VERIFY tables: **confirmed** (read in the panel's own source/docs) · **contradicted** (source disagrees with the reference note) · **unresolved** (could not be confirmed from a reachable official source; the adapter must be defensive and the item needs a live check on a real panel).

## 0. Current panel layer in this repo (ground truth to preserve)

Only one client exists: `core/services/panel_client.py::MarzbanClient`. Despite the name it speaks **PasarGuard** (payload uses `group_ids`, `proxy_settings`, `hwid_limit`, `PUT /api/user/by-id/{id}`).

Auth (`MarzbanClient.login`): `POST {base}/api/admin/token`, form-encoded `grant_type=password&username=…&password=…`, response `access_token`, then `Authorization: Bearer …`. One re-login on HTTP 401 (`_request`). Headers: custom `User-Agent`, `Accept: application/json`. No timeouts, default TLS verification.

### Exact create-user request the bot sends today (`MarzbanClient.create_user`)

```
POST /api/user
{
  "username": "U_<telegram_id>_<tx_id>_<created_ts>"          # free test: "TEST_<telegram_id>_<ts>"
  "status": "active",
  "data_limit": <int bytes>,                                  # 0 = unlimited
  "hwid_limit": <int> | null,                                 # null when plan.user_limit == 0
  "expire": "<unix ts as STRING>" | "0",
  "note": "",
  "group_ids": [1] | [3],                                     # HARD-CODED, see below
  "proxy_settings": {"vmess": {}, "vless": {}, "trojan": {}, "shadowsocks": {"method": "aes-256-gcm"}},
  "data_limit_reset_strategy": "no_reset"
}
```
Only `subscription_url` from the response is used. Usage monitoring uses `GET /api/user/{username}` → `data_limit`, `used_traffic`, `expire`, `status`.
`update_user` (`PUT /api/user/by-id/{id}`), `delete_user`, `revoke_sub`, `reset_usage`, `get_users` (`/api/system/users`), `get_resources` (`/api/system/resources`) exist but have **no callers**. The two `/api/system/*` paths were not found in the PasarGuard or Marzban routers I fetched — treat them as dead code.

### Hard-coded `group_ids` (3 places, identical expression)
`[1] if server.username == 'Mahdi@devz_1234' else [3]` in:
- `bot/handlers/admin_handlers.py::admin_approve_transaction` (create after receipt approval)
- `bot/handlers/user_handlers.py::process_wallet_buy`
- `bot/handlers/user_handlers.py::free_test_generate`

### Call sites (everything that touches a panel)
| Operation | Where |
|---|---|
| connection test at registration | `admin_handlers.py::_test_marzban_connection` (login only) |
| create | `admin_approve_transaction`, `process_wallet_buy`, `free_test_generate` |
| read usage | `process_service_monitoring` (user), `admin_customer_service_monitor` (admin) |
| renew / disable / delete / sync | **none exist** |

Panel username is not stored; it is recomputed from `tx.id` and `tx.created_at`. Username length: `U_` + ≤10 digits + `_` + tx id + `_` + 10 digits (≈ 24–32 chars) — close to Marzban's 32 limit.

## 1. PasarGuard

Sources (official repo `PasarGuard/panel`, branch `dev`): `app/routers/group.py`, `app/models/group.py`, `app/routers/user.py`, `app/models/user.py`, `app/models/validators.py`, `app/routers/admin.py`, `app/operation/group.py`, `app/operation/permissions.py`; docs https://docs.pasarguard.org/zh/panel/groups/. Secondary DeepWiki page was unreachable (HTTP 429 bot checkpoint) — not needed.

### Auth
`POST /api/admin/token` (`OAuth2PasswordRequestForm`) → `{"access_token": "..."}`; 401 on bad credentials, 403 `"your account has been disabled"`. Bearer token afterwards. (admin.py)

### Endpoints the adapter will use
| Purpose | Request | Notes |
|---|---|---|
| list groups | `GET /api/groups` → `{"groups":[{"id","name","inbound_tags":[…],"is_disabled","total_users"}],"total":n}` | needs permission `groups.read`; result is already filtered by the admin's `allowed_group_ids` (`apply_group_access`). Query `offset`/`limit` default to none (all). |
| list groups (lightweight) | `GET /api/groups/simple` → `{"groups":[{"id","name"}],"total":n}` | permission `groups.read_simple`; **no `is_disabled` field** → fallback only. |
| create user | `POST /api/user` | `group_ids` **must be non-empty** (`ListValidator.not_null_list`). |
| get user | `GET /api/user/{username}` (also `/by-id/{id}`, `/by-username/{u}`) | 404 if missing. |
| modify (extend) | `PUT /api/user/{username}` (also `/by-id/{id}`) | `null`/omitted fields = no change. |
| disable/enable | `PUT /api/user/{username}/disabled` body `{"disabled": true|false}` | also `status` via modify. |
| delete | `DELETE /api/user/{username}` → 204 | |
| ping | token request + `GET /api/groups` (cheap, also proves `groups.read`) | |

Sample group response (from `GroupResponse`): `{"id": 3, "name": "premium", "inbound_tags": ["vless-443"], "is_disabled": false, "total_users": 12}`.

### Why a missing/wrong `group_ids` produces a "config without nodes"
Group → inbound tags → hosts. A user in no enabled group sees **no hosts** (empty subscription); a disabled group is excluded from the calculation. Group names are 3–64 chars `a-z0-9`; IDs are DB auto-increment and can be re-issued if a provider deletes/recreates groups. (docs groups page)

### VERIFY resolution
| Item | Result |
|---|---|
| token endpoint/format | **confirmed** (`admin.py::admin_token`) |
| `expire` format | **confirmed (type)**: model is `datetime \| int \| None`; docs say "UTC datetime, `0` = unlimited". The bot sends a numeric **string** and works in production → keep byte-for-byte. |
| status values / disable | **confirmed**: modify accepts `active`, `disabled`, `on_hold`; dedicated `PUT …/disabled` exists. `limited`/`expired` are read-only states (docstring). |
| `GET /api/groups` envelope & fields | **confirmed** (`GroupsResponse`, `GroupResponse`) |
| `subscription_url` absolute? | **unresolved**: field is a plain string, generated in the operation/subscription layer that I did not fetch. Adapter must normalise (prefix `panel_config.sub_url_template`/panel origin when it starts with `/`). |
| username rules | **confirmed**: 3–128 chars, `[a-zA-Z0-9-_@.]`, no consecutive special chars (`UserValidator.validate_username`). |
| restricted admins | **confirmed**: `allowed_group_ids` restricts both listing and assignment (`permissions.py`) → only send IDs returned by the live listing with the bot's own credentials. |

## 2. Marzban

Sources (official repo `Gozargah/Marzban`, branch `master`): `app/models/user.py`, `app/models/proxy.py`, `app/routers/user.py`, `app/routers/system.py`. The running panel's `/docs` was not reachable (no test panel) → **unresolved** whether the path is `/docs` on every install.

### Endpoints
| Purpose | Request | Notes |
|---|---|---|
| auth | `POST /api/admin/token` (form) → `access_token` | not fetched directly (same lineage as PasarGuard); **unresolved-but-consistent** with `Admin.get_current` usage. |
| inbounds | `GET /api/inbounds` → `{"vless":[{"tag","protocol","network","tls","port"}], "vmess":[…], …}` | any logged-in admin (`system.py`). |
| create | `POST /api/user` | see payload below. |
| get | `GET /api/user/{username}` | |
| modify | `PUT /api/user/{username}` | `null`/omitted = no change; protocols must be enabled on the server else 400. |
| delete | `DELETE /api/user/{username}` | |
| reset usage | `POST /api/user/{username}/reset` | |

### Create payload (from `UserCreate` + example)
```
{"username": "...", "status": "active",
 "proxies": {"vless": {}, "vmess": {}},           # required, non-empty
 "inbounds": {"vless": ["<tag>", …], "vmess": ["<tag>", …]},
 "expire": 0 | <unix ts int>, "data_limit": 0 | <bytes>,
 "data_limit_reset_strategy": "no_reset", "note": ""}
```
Response: `UserResponse` with `username, status, used_traffic, lifetime_used_traffic, expire, data_limit, links, subscription_url, proxies, inbounds, excluded_inbounds, created_at`.

### VERIFY resolution
| Item | Result |
|---|---|
| `GET /api/inbounds` shape | **confirmed** (`Dict[ProxyTypes, List[ProxyInbound]]`) |
| omitted `inbounds` = all of the given protocols | **confirmed** (`UserCreate.validate_inbounds` fills every tag per protocol), but the adapter will still send them explicitly. Inbounds for protocols not in `proxies` are silently dropped. |
| username rules | **confirmed**: regex `^(?=\w{3,32}\b)[a-zA-Z0-9-_@.]+…` → **3–32 chars** (the bot's current naming can reach 32). |
| `subscription_url` absolute/relative | **confirmed possible relative**: built as `{XRAY_SUBSCRIPTION_URL_PREFIX}/{XRAY_SUBSCRIPTION_PATH}/{token}`; empty prefix ⇒ relative. Adapter normalises; `panel_config.sub_url_template` overrides. |
| status values | **confirmed**: create `active`/`on_hold`; modify `active`/`disabled`/`on_hold`; read adds `limited`/`expired`. `on_hold` cannot be combined with `expire`. |
| extend semantics | **unresolved by docs** (no API rule). Adapter rule (to unit-test and live-check): `expire` = max(now, old_expire) + days·86400 (never in the past); `data_limit` = old_limit + add_bytes (it is a total); status set back to `active` if it was `expired`/`limited`. |
| `/docs` path | **unresolved** |

## 3. Hiddify Manager

Sources: official how-to https://hiddify.com/manager/contribution/How-to-use-API-in-HiddifyManager-project ; official panel repo `hiddify/hiddifypanel` (`hiddifypanel/auth.py`, `…/restapi/v2/admin/__init__.py`, `…/admin/user_api.py`, `…/admin/users_api.py`, `…/admin/schema.py`, `…/panel/__init__.py`, `…/panel/info.py`). The panel's built-in Swagger (Admin → Settings → API) is the per-install authority and was not reachable.

### Auth
Header `Hiddify-API-Key: <admin UUID>`; `auth_before_request` resolves it as an **admin** when the URL is under the admin proxy path (`auth.py`). The request URL always contains the proxy path: `https://<domain>/<proxy_path>/api/v2/…`.

### Endpoints (all prefixed `/<admin_proxy_path>/api/v2`)
| Purpose | Request | Notes |
|---|---|---|
| ping | `GET /panel/ping/` (and `GET /panel/info/` → version) | **the official how-to says `/panel/version`; the source registers `/info/` and `/ping/`** → version-dependent; adapter tries `ping/`, falls back to `info/`. |
| list users | `GET /admin/user/` | returns **404 "You have no user"** when the admin has zero users → never use it as a health check. |
| create | `POST /admin/user/` | `uuid` optional (server generates). Server enforces admin limits (400 "User limit reached…"). |
| get | `GET /admin/user/{uuid}/` | 404 if missing/out of scope. |
| update | **`PATCH`** `/admin/user/{uuid}/` | not PUT. |
| delete | `DELETE /admin/user/{uuid}/` | returns `{"status":200,"msg":"ok"}`. |

### User object (`UserSchema`)
`uuid, name, usage_limit_GB (float), package_days (int), mode (UserMode), last_online, last_modified_time, start_date (YYYY-MM-DD), current_usage_GB, last_reset_time, comment, added_by_uuid, telegram_id, enable, deleted, is_active, …`. **No subscription URL field** in the schema.

Sample create body (adapter): `{"uuid":"<deterministic uuid5>", "name":"<username>", "usage_limit_GB": 50.0, "package_days": 30, "mode":"no_reset", "enable": true, "comment":"…"}`.

### VERIFY resolution
| Item | Result |
|---|---|
| v2 user endpoints | **confirmed** (routes above) |
| header auth | **confirmed** (`auth.py`) |
| field names / GB float units | **confirmed** (`UserSchema`) |
| `mode` values | **unresolved**: `UserMode` enum not fetched; third-party clients report `no_reset\|daily\|weekly\|monthly`. Adapter sends `no_reset` and a live check is required. |
| subscription URL | **contradicted** (reference expected it in the response): it must be composed `https://<domain>/<client_proxy_path>/<uuid>/`; the exact shape is **unresolved** → `panel_config.sub_url_template` (default as above) + owner confirmation. |
| extend via `package_days`/`start_date` | **unresolved**: `PatchUserSchema` accepts both, but open issue hiddify/Hiddify-Manager#5246 reports `start_date`/`last_reset_time` not changing for an expired user on some versions. Rule to implement and live-test: active → `package_days += add_days`; expired → set `start_date = today`, `package_days = add_days`, reset usage (`current_usage_GB = 0`) — if the panel ignores it, fail with a clear `PanelRejected`/`PanelCapabilityError` instead of lying. |
| disable/enable | **confirmed**: `enable` flag in `PatchUserSchema`. |
| groups/inbounds | **confirmed none** → `supports_targets = False`. |

## 4. Cross-panel contract decisions (for the plan)
- Adapter module location: new package `core/panels/` (the repo has only `core/services/panel_client.py`; the old client is kept until all call sites move).
- All HTTP through one shared `aiohttp` session helper: connect 5 s / total 20 s, `ssl` verification on unless `panel_config.verify_ssl is False`.
- Hiddify `remote_id` = uuid (deterministic `uuid5(NAMESPACE, f"{server_id}:{order_ref}")`) → create-after-lookup is trivially idempotent.
- Quota unit conversion in exactly one place per adapter (bytes ↔ GB).
- Subscription URL normalised to absolute in the adapter; never logged.

## 5. Open items that need the owner or a real panel
1. A running PasarGuard / Marzban / Hiddify instance (or sandbox credentials) to confirm the **unresolved** rows above before the Marzban/Hiddify adapters are called "done".
2. Hiddify: admin proxy path, client proxy path and whether subscription links use the same domain.
3. Which `groups.read` permission the existing PasarGuard bot admins have (otherwise the `/groups/simple` fallback applies, and "disabled groups" cannot be excluded).
