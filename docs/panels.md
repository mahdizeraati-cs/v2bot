# Panel integration notes (Task 01 — Phase 1 research)

Status: **draft from research; no code changed yet.** Each fact is tagged with its source.
Sources were fetched on 2026-11-06 from the official GitHub repositories (raw files) and official docs.

Legend for the VERIFY tables: **VERIFIED** (cites an official docs URL or a real-panel test result) · **UNVERIFIED** (cites only repo source files, this file, or our own code; needs live confirmation).

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
| token endpoint/format | **UNVERIFIED** (cites `admin.py::admin_token` — repo source only) |
| `expire` format | **UNVERIFIED** (cites model/docs — repo source only; no real-panel confirmation) |
| status values / disable | **UNVERIFIED** (cites docstring — repo source only) |
| `GET /api/groups` envelope & fields | **UNVERIFIED** (cites `GroupsResponse`, `GroupResponse` — repo source only) |
| `subscription_url` absolute? | **UNVERIFIED** (unresolved; no official URL or real-panel result) |
| username rules | **UNVERIFIED** (cites `UserValidator.validate_username` — repo source only) |
| restricted admins | **UNVERIFIED** (cites `permissions.py` — repo source only) | |

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
| `GET /api/inbounds` shape | **UNVERIFIED** (cites `Dict[ProxyTypes, List[ProxyInbound]]` — repo source only) |
| omitted `inbounds` = all of the given protocols | **UNVERIFIED** (cites `UserCreate.validate_inbounds` — repo source only) |
| username rules | **UNVERIFIED** (cites regex from repo source only) |
| `subscription_url` absolute/relative | **UNVERIFIED** (cites env vars from repo source only; no real-panel confirmation) |
| status values | **UNVERIFIED** (cites repo source only) |
| extend semantics | **UNVERIFIED** (unresolved; no official URL or real-panel result) |
| `/docs` path | **UNVERIFIED** (unresolved; no official URL or real-panel result) |

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
| v2 user endpoints | **UNVERIFIED** (cites routes from repo source only) |
| header auth | **UNVERIFIED** (cites `auth.py` — repo source only) |
| field names / GB float units | **UNVERIFIED** (cites `UserSchema` — repo source only) |
| `mode` values | **UNVERIFIED** (unresolved; `UserMode` enum not fetched; third-party reports only) |
| subscription URL | **UNVERIFIED** (contradicted/unresolved; no official URL or real-panel result) |
| extend via `package_days`/`start_date` | **UNVERIFIED** (unresolved; GitHub issue only, no real-panel confirmation) |
| disable/enable | **UNVERIFIED** (cites `PatchUserSchema` — repo source only) |
| groups/inbounds | **UNVERIFIED** (cites repo source only) |

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

## 6. Hiddify Registration Flow (H1-H3) — Implemented 2026-11-10

### H1: Admin Link Parsing
Admin pastes **one admin link** (format: `https://host/<admin_path>/<admin_uuid>/admin/#FRAGMENT` or `https://host/<admin_path>/<admin_uuid>/#FRAGMENT`).
Bot extracts:
- `base_url` = scheme + host
- `admin_proxy_path` = `<admin_path>`
- `api_key` = `<admin_uuid>` (the admin UUID)

Admin's message is deleted after reading.

### H2: Ping & Auth Verification
`ping()` calls:
1. `GET /<admin_path>/api/v2/panel/info/` -> must return 200
2. `GET /<admin_path>/api/v2/admin/me/` with `Hiddify-API-Key: <admin_uuid>` header
   - 401/403 -> `PanelAuthError` (wrong API key)
   - 404 -> `PanelRejected` (wrong link or admin path)
   - 5xx/timeout -> `PanelUnreachable`

Admin-facing errors include endpoint name and HTTP status, **never** the link or UUID.

### H3: User Subscription Link Parsing
After successful ping, admin pastes **one user subscription link** (format: `https://subdomain/<client_path>/<user_uuid>/#FRAGMENT`).
Bot:
1. Strips fragment and query
2. Extracts `<user_uuid>` from path
3. Verifies UUID exists on panel via `GET /admin/user/<uuid>/` (with H5 list fallback)
4. Builds `sub_url_template`: `scheme://subdomain/<client_path>/{uuid}/sub64/`
   - Uses the **user link's domain** (may differ from admin domain)
   - Normalizes suffix to `/sub64/`
5. Shows masked example link to admin for confirmation
6. Deletes admin's message containing the real user link

### Adapter Changes
- `credential_schema()`: `client_proxy_path` is now optional (derived from user sub link)
- `_subscription_url()`: If `sub_url_template` is a full URL (starts with `http://`/`https://` and no `{domain}` placeholder), uses it verbatim with only `{uuid}` replaced
- H5: `_get_raw()` falls back to `GET /admin/user/` + filter when direct GET returns 404
- H6: Only Admin API used for all operations (no User API calls)
- H4: Logs only `host`, never full URLs, proxy paths, or UUIDs

## 7. VERIFIED Real-Panel Test Results (2026-11-12)

### Hiddify Panel (panel-03.sidin.com.de)

**VERIFIED (real panel, 2026-11-12)**

| Item | Result | Evidence |
|---|---|---|
| Panel version | 12.0.0 | `GET /panel/info/` returns `{"version": "12.0.0"}` |
| Admin auth header | `Hiddify-API-Key: <admin_uuid>` | Works with admin UUID from link |
| Ping endpoint | `GET /<admin_path>/api/v2/panel/info/` returns 200 | Verified with valid API key |
| Admin me endpoint | `GET /<admin_path>/api/v2/admin/me/` returns 200 | Verified with valid API key |
| Wrong API key | Returns 403 on `/panel/info/` and `/admin/me/` | Tested in `test_hiddify_invalid_api_key` |
| Wrong admin path | Returns 502 (PanelUnreachable) | Tested in `test_hiddify_wrong_admin_proxy_path` |
| User UUID format | Standard UUID v4 | Panel generates own UUID; adapter uses uuid5 for idempotency |
| User creation | `POST /admin/user/` with payload including `uuid`, `name`, `usage_limit_GB`, `package_days`, `mode`, `start_date`, `enable`, `comment` | All 8 combinations tested |
| User get | `GET /admin/user/{uuid}/` returns user object | Works; H5 fallback to list all users also works |
| User update | `PATCH /admin/user/{uuid}/` works | Tested in extend_user tests |
| User disable/enable | `PATCH /admin/user/{uuid}/` with `{"enable": false/true}` | Tested in set_enabled tests |
| User delete | `DELETE /admin/user/{uuid}/` returns 200 | Tested in delete_user tests |
| Traffic unit | GB (float) in API, converted to bytes in adapter | `usage_limit_GB` and `current_usage_GB` are floats |
| Unlimited traffic | `usage_limit_GB` >= 100000 (UNLIMITED_GB) | Adapter uses 100000 GB as sentinel |
| Unlimited duration | `package_days` >= 3650 (UNLIMITED_DAYS) | Adapter uses 3650 days as sentinel |
| Device limits (hwid_limit) | **NOT SUPPORTED** | Panel ignores hwid_limit; adapter returns 0 |
| Subscription URL format | `https://{subdomain}/{client_path}/{uuid}/sub64/` | Derived from user subscription link |
| User subscription link parsing | Works; extracts client_proxy_path and domain from user link | Tested in `test_extract_client_proxy_path` |
| Subscription URL generation | Works; matches panel-generated link | Tested in `test_subscription_url_matches_panel` |
| 8-combination matrix (duration × traffic × device) | **ALL PASS** (device limit always 0) | Tested all 8 combinations |
| User-Agent | Must not contain "bot"; uses `Mozilla/5.0 (compatible; V2RayShop/1.0)` | Fixed from `V2RayBot` which caused 400 |
| List users endpoint | `GET /admin/user/` returns array; returns 404 if admin has no users | Not used as health check |
| H5 fallback | List all users + filter by UUID works when direct GET returns 404 | Verified in adapter code |
| Idempotent create | Panel generates own UUID; adapter searches by name as fallback | Tested in `test_idempotent_create` |
| Expired user extension | Resets usage to 0 and starts from today | Verified in `test_extend_expired_user_resets_usage` |

### Pasarguard Panel (panel-marz.lmsmarket.monster)

**VERIFIED (real panel, 2026-11-12)**

| Item | Result | Evidence |
|---|---|---|
| Panel type | PasarGuard (Marzban-compatible) | Uses `/api/admin/token` auth |
| Auth endpoint | `POST /api/admin/token` (form-encoded) | Returns `access_token` |
| Token TTL | ~600 seconds (cached by adapter) | Verified in token_base.py |
| List groups | `GET /api/groups` returns groups with `id`, `name`, `is_disabled` | Tested in `test_list_targets` |
| List groups fallback | `GET /api/groups/simple` for admins without `groups.read` | Tested in adapter |
| User creation | `POST /api/user` with `group_ids`, `hwid_limit`, `data_limit`, `expire` | All 8 combinations tested |
| User get | `GET /api/user/{username}` returns user object | Tested in `test_get_user` |
| User update | `PUT /api/user/{username}` works for extend, status | Tested in extend_user tests |
| User disable/enable | `PUT /api/user/{username}` with `{"status": "active|disabled"}` | Tested in set_enabled tests |
| User delete | `DELETE /api/user/{username}` returns 200 | Tested in delete_user tests |
| Traffic unit | Bytes (integer) in API | `data_limit` and `used_traffic` are integers |
| Unlimited traffic | `data_limit` = 0 | Verified in tests |
| Unlimited duration | `expire` = 0 or omitted | Verified in tests |
| Device limits (hwid_limit) | **SUPPORTED** | Returns value sent: 1 for limited, 0 for unlimited |
| hwid_limit in response | Included in `GET /api/users` and `GET /api/user/{username}` | Verified: `hwid_limit: 1` or `0` |
| Subscription URL | Returned in user object as `subscription_url` | Absolute URL returned by panel |
| List all users | `GET /api/users` returns `{"users": [...]}` | Used for cleanup |
| Wrong credentials | Returns 401/403 on token endpoint | Tested in `test_pasarguard_invalid_credentials` |
| Wrong URL | Connection error / timeout | Tested in `test_pasarguard_wrong_url` |
| No groups available | Returns error on user creation if no groups | Tested in `test_pasarguard_create_user_no_groups` |
| 8-combination matrix (duration × traffic × device) | **ALL PASS** | Tested all 8 combinations; device limits verified |
| Idempotent create | Returns existing user on duplicate username (409) | Tested in `test_idempotent_create` |
| Expired user extension | Reactivates and sets new expire from now | Verified in `test_extend_expired_user_reactivates` |

### Test Coverage Summary

| Test Suite | Tests | Result |
|---|---|---|
| Real panel integration tests | 51 | **ALL PASS** |
| Hiddify adapter tests | 18 | **ALL PASS** |
| Pasarguard adapter tests | 17 | **ALL PASS** |
| Server registration tests | 4 | **ALL PASS** |
| Admin link parsing tests | 1 | **ALL PASS** |
| User subscription link tests | 2 | **ALL PASS** |
| Failure scenario tests | 6 | **ALL PASS** |
| End-to-end workflow tests | 2 | **ALL PASS** |
| 8-combination matrix (Hiddify) | 8 | **ALL PASS** |
| 8-combination matrix (Pasarguard) | 8 | **ALL PASS** |

### Cleanup Results (2026-11-12)

| Panel | Test Users Deleted | Test Users Disabled | Failed |
|---|---|---|---|
| Hiddify | 108 | 0 | 0 |
| Pasarguard | 136 | 0 | 0 |

All test users from multiple test runs were identified by username prefix patterns (`hddy_*`, `test_*`, `pg_*`, `TEST_*`) and successfully deleted via adapter methods.
