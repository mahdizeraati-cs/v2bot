# Architecture notes (Task 00 — discovery, read-only)

Scope: read from `main.py`, `bot/**`, `core/**`, `docker-compose.yml`, `requirements.txt`, `alembic.ini`. `.env` was not read. Anything not found is marked `NOT FOUND`.

## A. Module map

| Module | Purpose / main symbols |
|---|---|
| `main.py::main` | Entry point. Builds async engine + `async_sessionmaker(expire_on_commit=False)` (L77-79), `Bot` (HTML parse mode, optional `PROXY_URL`), `Dispatcher()` (L95), APScheduler, middleware, routers, `delete_webhook(drop_pending_updates=True)` + `start_polling` (L114-115). `notify_owner_of_crash` sends raw HTTP to Telegram on crash. |
| `bot/main.py` | Empty file (0 bytes). |
| `bot/config.py` | `MESSAGES`, `BUTTONS`, `ACTIVE_PANELS`, `SALES_PLANS` dicts. `ACTIVE_PANELS`/`SALES_PLANS` are not imported by handlers (only `BUTTONS`, `MESSAGES` are) — legacy. |
| `bot/middlewares/database.py::DatabaseMiddleware` | Opens one session per update and injects `data["db_session"]`. No commit/rollback; handlers commit themselves. |
| `bot/states.py` | All FSM `StatesGroup`s (see J). |
| `bot/handlers/admin_handlers.py` | ~3640 lines, `router`; all vendor/owner panel handlers (see D). |
| `bot/handlers/user_handlers.py` | ~1790 lines, `router`; customer flows (start, buy, wallet, receipt, support, services, free test + force-join). |
| `bot/handlers/__init__.py`, `bot/keyboards/__init__.py` | Empty. |
| `core/database/models.py` | Single-file models (NOT a `models/` package as AGENTS.md says). |
| `core/database/database.py` | Module-level `engine`, `async_session` (raises at import if `DATABASE_URL` missing). Not used by `main.py`. |
| `core/database/crud.py` | `get_or_create_user`, `_get_next_vendor_round_robin`. |
| `core/services/panel_client.py::MarzbanClient` | Only panel client (login, create/get/update/delete user, revoke_sub, reset_usage, get_users, get_resources). |
| `core/utils/backup.py::perform_database_backup` | Raw asyncpg COPY of every public table to CSV zip, sent to `OWNER_ID`. |
| `core/database/migrations/` | Alembic (`alembic.ini::script_location`); one revision `versions/78aefc94582e_init_database.py`. |
| Root scripts | `reset_db.py`, `res_db.py`, `reset_alembic.py`, `restore_backup.sh` (destructive, not read; never run), `test_panel.py` (not read). |

## B. Database

Models: `core/database/models.py`. Alembic: `core/database/migrations/versions/` (one revision, `78aefc94582e`, down_revision None). `migrations/env.py` rewrites `postgresql://` -> `postgresql+asyncpg://` (L28-29), same as `main.py`. `env.py` imports `Base` before the `sys.path.append` (L13 vs L16) — works only if run from repo root.

| Table (model) | Columns (type, nullability) | FKs / constraints |
|---|---|---|
| `vendors` (`Vendor`) | id int PK; telegram_id BigInt unique+index; name str50; card_number str20 NULL; wallet_address str100 NULL; is_active bool; redirect_to_id int NULL; redirect_target_id int NULL; created_at tz | both redirect cols FK vendors.id ON DELETE SET NULL |
| `servers` (`Server`) | id; vendor_id NULL; is_shared bool; name str50; panel_url str255; username str50; **password str255 (plaintext)**; total_capacity Float; is_active bool; is_deleted bool server_default false | vendor_id FK vendors CASCADE |
| `plans` (`Plan`) | id; vendor_id; server_id; title str100; volume_gb **Float**; days int; user_limit int; price **Float**; description str255 NULL; is_active; is_deleted (server_default false) | vendor_id CASCADE; server_id CASCADE |
| `vendor_servers` (`VendorServer`) | id; vendor_id; server_id | both CASCADE; **no unique constraint** on the pair |
| `users` (`User`) | id; telegram_id BigInt unique+index; vendor_id (NOT NULL); wallet_balance **Float**; created_at; has_received_test bool | vendor_id FK vendors (no ondelete) |
| `force_join_channels` | id; vendor_id; chat_id str100; title str255; url str255 | vendor CASCADE |
| `transactions` (`Transaction`) | id; user_id; vendor_id; server_id NULL; plan_id NULL; amount **Float**; discount_percent int; original_amount int; discount_code_id NULL; origin_vendor_id NULL; receipt_file_id str255 NULL; status str20 (free string: pending/approved/rejected/failed/canceled); destination_card str100 NULL; created_at; updated_at | user CASCADE; vendor CASCADE; server/plan/discount/origin SET NULL |
| `discount_codes` | id; vendor_id; code str50; discount_percent int; is_active; created_at | unique (vendor_id, code) |
| `tickets` | id; user_id; vendor_id; message_text str1000; status str20 (pending/answered/closed); created_at | CASCADE both |

- Money type: `Float` for `wallet_balance`, `Transaction.amount`, `Plan.price` (violates the AGENTS.md "no float" rule); `Transaction.original_amount` is Integer. Unit: toman (`int(tx.amount)`, rial = toman*10 in captions).
- Enums: none; all statuses are free strings. No CHECK constraints.
- Indexes: only unique indexes on `vendors.telegram_id`, `users.telegram_id`. No index on `transactions.status/vendor_id/user_id`, `users.vendor_id`.
- NOT FOUND: payment/receipt table, event/audit table, wallet ledger, settings table, roles table, server panel_type column, per-server TLS flag, panel username/subscription id column on transactions.
- Comment in `models.py` L6-8 mentions a pending migration; the only revision already contains `redirect_target_id`, `discount_*`, `is_deleted`.

## C. Identity and roles

- Owner: env `OWNER_ID` compared at call time (`admin_handlers.py::get_admin_panel_content` L58-59, `admin_view_servers` L699-700, `admin_reports` L3443-3444, `admin_manage_vendors_menu` L3497-3498, `admin_add_vendor_start` L3553-3554, `admin_server_details` L1084-1085, `crud.py::get_or_create_user` L43-47).
- "Admin/seller" == a row in `vendors` with `telegram_id == from_user.id` (`get_admin_panel_content` L53). There is no role column; owner is just a vendor whose id equals `OWNER_ID` (auto-created as vendor "Owner" on `/start`, `crud.py` L47-58). `vendors.is_active` is NOT checked for panel access (`get_admin_panel_content` only displays it).
- Customer == row in `users` (`User.telegram_id`), permanently bound to one `vendor_id` (`crud.py::get_or_create_user` L64-66: existing user never re-assigned).
- Admin panel entry: `/admin` or `/panel` (`cmd_admin_panel`). Partners are created by owner only: `admin_handlers.py::process_partner_telegram_id` / `process_partner_name` (create `Vendor`).
- Assignment of a new customer: deep link `ref_|start_|vendor_<vendor.id>` (`user_handlers.py::cmd_start` L52-63) if the vendor is active (`crud.py` L70-77), else round-robin.
- Round-robin (`crud.py::_get_next_vendor_round_robin`): no stored cursor. It takes `vendor_id` of the most recent user (`ORDER BY users.id DESC LIMIT 1`), then the first active vendor with `id >` that, else the first active vendor. Consequences: one active vendor -> always that vendor; new vendor with a higher id gets the next customer; a disabled vendor is skipped (existing users stay with it); deep-link users shift the cursor; two concurrent first-time users can read the same "last user" and get the same vendor (no lock). The owner is included in the rotation (normal active vendor).
- Redirect: `Vendor.redirect_target_id` (set via `admin_redirect_menu`/`process_redirect_target`) sends payments/tickets to another vendor (see F). `redirect_to_id` column exists but is NOT FOUND in any handler.

## D. Handler inventory

Admin router is included first (`main.py` L109-110). **No router-level filter or middleware performs role checks**; each handler does its own `select(Vendor)` lookup (or none). "Vendor-only" below means `Vendor.telegram_id == from_user.id`.

| file::function | trigger | role check | data scope |
|---|---|---|---|
| admin::cmd_admin_panel | `/admin`,`/panel` | vendor row | own vendor |
| admin::callback_back_to_admin_panel | `back_to_admin_panel` | vendor row (via content fn); clears FSM | own |
| admin::close_panel | `close_admin_panel` | NONE | deletes message |
| admin::admin_receipts_list | `admin_receipts` | vendor row | `Transaction.vendor_id == vendor.id`, pending, with receipt |
| admin::admin_receipt_detail | `adm_rcp_<tx>` | **NONE** | any tx by id (IDOR) |
| admin::admin_approve_transaction | `admin_approve_tx_<tx>` | **NONE** | any pending tx by id (IDOR) |
| admin::admin_reject_transaction | `admin_reject_tx_<tx>` | **NONE** | any pending tx by id (IDOR) |
| admin::ask_vendor_card / process_vendor_card | `admin_payment_info`; FSM `AdminStates.waiting_for_card_number` | vendor row | own card |
| admin::admin_view_servers | `admin_view_servers` | vendor row; owner sees selective-share button | own + shared servers |
| admin::start_add_server | `add_srv_selective`,`add_srv_private` | **NONE** (selective not owner-checked) | FSM |
| admin::srv_name/srv_url/srv_user/srv_pass | FSM `AddServerStates.*` | srv_pass: vendor row | creates `Server` |
| admin::toggle_vendor_in_sharing / save_server_with_vendor_sharing | FSM `waiting_for_vendor_selection`, `srv_togv_<id>`, `srv_save_vendor_sharing` | **NONE** (state-gated only) | creates `VendorServer` rows |
| admin::admin_server_details | `srv_det_<id>` | owner or server owner for buttons; **view has no scope check** | any server by id (shows panel_url) |
| admin::toggle_server_status | `srv_tog_<id>` | **NONE** | any server (IDOR), deactivates its plans |
| admin::delete_server | `srv_del_<id>` | **NONE** | any server (IDOR), soft delete |
| admin::admin_manage_plans_menu | `admin_manage_plans` | NONE | menu |
| admin::add_plan_select_server | `admin_add_plan_sel_srv` | vendor row | own+shared active servers |
| admin::plan_title_start | `addp_s_<srv>` | **NONE**; server id not re-validated | FSM |
| admin::plan_title/volume/days/user_limit/price/description | FSM `AddPlanStates.*` | description: vendor row; **server access not re-checked** | creates `Plan` |
| admin::admin_view_categories_by_server, admin_view_plans_in_server | `adm_view_srv_plans`, `adm_cat_<srv>` | vendor row | own+shared servers |
| admin::admin_show_plan_details / admin_toggle_plan / admin_delete_plan / admin_edit_price / admin_process_new_price | `adm_p_`,`adm_tog_`,`adm_del_`,`adm_edp_`; FSM `EditPlanStates` | vendor row + `_check_plan_access` | plans on own/shared servers (shared vendors can edit owner's plans) |
| admin::admin_support_tickets_list | `admin_support_tickets` | vendor row | `Ticket.vendor_id == vendor.id` |
| admin::admin_show_ticket / admin_reply_ticket_start / admin_reply_ticket_send / admin_close_ticket | `adm_tk_`,`adm_tkr_`,`adm_tkc_`; FSM `AdminTicketStates` | **NONE** | any ticket by id (IDOR) |
| admin::admin_force_join_menu / admin_force_join_add / process_force_join_channel_data | `admin_force_join`,`fjc_add`; FSM `AdminForceJoinStates` | vendor row (add/menu) | own channels |
| admin::admin_force_join_delete | `fjc_del_<id>` | **NONE** | any channel (IDOR) |
| admin::admin_my_customers, admin_customers_list | `admin_my_customers`, `adm_cust_list_<page>` | vendor row | `User.vendor_id == vendor.id` |
| admin::admin_broadcast_start / process_broadcast_message | `adm_cust_broadcast`; FSM `waiting_for_broadcast_message` | vendor row | own customers only; owner is NOT global |
| admin::admin_search_start / process_customer_search | `adm_cust_search`; FSM | vendor row | own customers |
| admin::admin_customer_detail / admin_wallet_charge_start / process_wallet_charge_amount / admin_customer_services / admin_customer_service_monitor | `adm_cust_det_`,`adm_cust_chg_`,`adm_cust_srv_`,`adm_usr_srv_` | vendor row + `user.vendor_id == admin_vendor.id` | own customers (proper IDOR check). Manual charge uses `float`, may be negative |
| admin::admin_discounts_menu / admin_discount_add_start / process_discount_code_input / process_discount_percent / admin_discount_delete | `admin_discounts`,`dc_add`,`delete_dc_<id>`; FSM `AdminDiscountStates` | vendor row; delete checks `vendor_id` | own codes. `dc_view_<id>` callback has NO handler |
| admin::admin_redirect_menu / process_redirect_target | `admin_redirect`; FSM `AdminRedirectStates` | vendor row | own vendor; target can be ANY vendor id (no consent/active check) |
| admin::admin_reports | `admin_reports` | vendor row; owner adds global stats | own tx sums |
| admin::admin_manage_vendors_menu, admin_add_vendor_start | `owner_manage_vendors`,`adm_ven_add` | owner check | all vendors. `adm_ven_<id>` callback has NO handler |
| admin::process_partner_telegram_id / process_partner_name | FSM `AdminPartnerStates` | **NONE** (state only) | creates `Vendor` |
| user::cmd_start | `/start [payload]` | none | creates/gets user |
| user::process_back_to_main, process_buy_new_service, process_server_selection, process_plan_selection | `back_to_main`,`buy_new_service`,`sel_srv_`,`buy_plan_` | user row | `buy_plan_` does NOT check plan belongs to user's vendor/active |
| user::apply_discount_start, skip_discount, process_discount_code, _create_purchase_invoice | `charge_req_`,`skip_discount`; FSM `PurchaseStates` | user row | `charge_req_` does not check plan scope |
| user::process_wallet_buy | `wallet_buy_<plan>_<dc>` | user row | `dc_id` client-supplied, not validated against vendor/active/usage; plan scope not checked |
| user::process_receipt_photo / process_receipt_invalid | FSM `WalletChargeStates.waiting_for_receipt` | none | tx from FSM data |
| user::ask_charge_amount / process_charge_amount | `charge_wallet`; FSM `waiting_for_amount` | user row | min 10,000 |
| user::process_user_profile, process_support, process_support_message, process_my_services | `user_profile`,`support`,`my_services` | user row | own |
| user::process_service_monitoring | `usr_srv_<tx>` | checks `tx.user.telegram_id == from_user.id` | own |
| user::free_test_start / free_test_verify / free_test_show_servers / free_test_generate | `free_test_*`, `req_test_<srv>` | user row | `req_test_` loads server by id with NO vendor-scope check (only `is_active`) |

## E. Panel layer

- Only `core/services/panel_client.py::MarzbanClient` (aiohttp). Auth: `POST /api/admin/token` form (`grant_type=password`, username, password) -> bearer token (`login`); relogin on 401 (`_request`). Endpoints: `GET /api/system/users`, `GET /api/system/resources`, `POST /api/user`, `GET /api/user/{username}`, `PUT /api/user/by-id/{id}`, `DELETE /api/user/{username}`, `POST /api/user/{username}/revoke_sub`, `POST /api/user/{username}/reset`. The payload uses `group_ids` (PasarGuard-style), not Marzban `inbounds`; class is named Marzban. No Hiddify code: NOT FOUND. No panel-type column: NOT FOUND.
- Create payload: username, status active, `data_limit`, `hwid_limit` (None if 0), `expire`, `group_ids`, `proxy_settings`, `data_limit_reset_strategy` (`MarzbanClient.create_user`). `expire` is sent as a numeric string of a unix timestamp (or `"0"`).
- **`group_ids` hard-coded** in three places: `admin_handlers.py::admin_approve_transaction` L476, `user_handlers.py::process_wallet_buy` L777, `user_handlers.py::free_test_generate` L1724 — all `[1] if server.username == 'Mahdi@devz_1234' else [3]` (keyed on a panel admin username committed in source). `update_user` also takes `gp_id`; no caller found.
- Timeouts: none (`aiohttp.ClientSession(trust_env=True)`, default timeout, `MarzbanClient._get_session`). TLS: default verification (no per-server flag). Login failure logs the response body (L48).
- Server registration FSM (`AddServerStates`): `add_srv_selective|add_srv_private` -> name -> url -> username -> password (`srv_pass`) -> `_test_marzban_connection` (login only) -> create `Server` (vendor-owned, `is_shared=False`) or, in selective mode, vendor multi-select (`srv_togv_`) -> `srv_save_vendor_sharing` creates `VendorServer` rows. The admin's password message is not deleted. No edit-server flow: NOT FOUND (only toggle/soft-delete).
- Username convention: `U_{telegram_id}_{tx.id}_{int(tx.created_at.timestamp())}` (approve L457, wallet_buy L754, monitors); free test `TEST_{telegram_id}_{ts}`. The panel username is NOT stored; it is recomputed.
- Lifecycle: create = approve / wallet buy / free test; renew = NOT FOUND in handlers (`update_user` unused); disable = NOT FOUND; delete = `delete_user` unused; usage = `get_user` in `process_service_monitoring` and `admin_customer_service_monitor`; sync = NOT FOUND.
- Panel failure on approve: tx already `approved` (L424) and the subscription text becomes `"خطا در ارتباط با پنل: {e}"` sent to the customer (leaks exception text); no retry state. Wallet buy on failure refunds and marks `failed` (L820-823).

## F. Payments and receipts

Customer flow (card-to-card): `buy_new_service` -> `sel_srv_` -> `buy_plan_` -> `charge_req_` (FSM `PurchaseStates`) -> optional discount code -> `_create_purchase_invoice`:
- wallet >= price: shows `wallet_buy_<plan>_<dc>` button (instant, no receipt): `process_wallet_buy` deducts the wallet, inserts tx `approved`, creates panel user, on failure refunds + `failed`. Read-modify-write on a float; double tap can race.
- else: `payable_via_card = price - wallet_balance`; inserts `Transaction(status="pending", amount=payable_via_card, vendor_id=target vendor)`. Random fee `(tx.id*73)%899+1` is added only in captions and recomputed everywhere (`_create_purchase_invoice` L650, `process_receipt_photo` L950, `admin_receipt_detail` L318, `admin_approve_transaction` L426). Wallet is deducted later, when the receipt photo arrives (`process_receipt_photo` L894-906), not at invoice time.
- Wallet top-up: `charge_wallet` -> `process_charge_amount` -> tx with `plan_id=None`, same receipt step.
- Receipt photo: `user_handlers.py::process_receipt_photo` (FSM `WalletChargeStates.waiting_for_receipt`). Stores `message.photo[-1].file_id` in `Transaction.receipt_file_id`, sets `pending`, sends the photo to `admin_tg_id` = telegram_id of the tx's vendor, then follows `vendor.redirect_target_id` AGAIN (L917-922). Since `tx.vendor_id` is already the redirect target, this is a second hop (a chain A->B->C would deliver to C). Approve/Reject buttons are on that message. Send failure is only logged.
- Reviewer: owner of the tx's `vendor_id` (customer's vendor or its redirect target). `admin_receipts_list` filters by `Transaction.vendor_id == vendor.id`.
- Approve: `admin_approve_transaction` — loads tx, checks `status == "pending"` in Python (no conditional UPDATE, no `FOR UPDATE`), sets `approved`, credits wallet (`amount + random_fee`, top-up) or creates panel user and DMs link + QR (plan). Deletes the reviewer's message and sets `receipt_file_id = None` (L446, L537) — receipt erased from DB and chat.
- Reject: `admin_reject_transaction` — sets `rejected`, refunds `wallet_used = actual_plan_price - amount` to wallet (derived from tx fields), deletes the reviewer's message, notifies user. No conditional update; concurrent rejects could refund twice.
- Tables/statuses: only `transactions`; statuses used: `pending`, `approved`, `rejected`, `failed`, `canceled`. No receipt table, no payment events/audit rows, no payment-history screen (only approved plan txs per customer in `admin_customer_services`). Auto-approve: NOT FOUND.
- Wallet: `users.wallet_balance` Float; manual adjust by vendor `process_wallet_charge_amount` (no log row).
- Pending txs created at invoice time (before receipt) appear in no list until `receipt_file_id` is set; abandoned pending txs are never cleaned.

## G. Settings

NOT FOUND: no settings table or key-value store. Per-vendor settings are columns on `vendors` (`card_number`, `wallet_address`, `redirect_target_id`, `is_active`) plus separate tables (`force_join_channels`, `discount_codes`). No "settings screen"; the admin menu is built in `admin_handlers.py::get_admin_panel_content`. Hard-coded: test config (75 MB, 1 day, hwid 1) in `free_test_generate`; min top-up 10,000 in `process_charge_amount`.

## H. Broadcast and forced join

- Broadcast: `admin_handlers.py::process_broadcast_message`. Recipients: `select(User).where(User.vendor_id == vendor.id)` (L2494) — only the sender's own customers; no owner-level global broadcast; text only. Runs inline with `asyncio.sleep(0.05)`; catches only `TelegramBadRequest` — NOT `TelegramRetryAfter` or `TelegramForbiddenError` (a blocked user aborts the loop). User text is sent with HTML parse mode unescaped. No background task/progress.
- Forced join: channels in `force_join_channels` per vendor (`ForceJoinChannel.vendor_id`). Managed in `admin_force_join_*`. Checked only for the free test: `user_handlers.py::free_test_start` / `free_test_verify` via `bot.get_chat_member` for `ForceJoinChannel.vendor_id == user.vendor_id` (L1452-1455, L1529-1532). Accepted statuses: member/administrator/creator. Any check error counts as "not joined". No inheritance from owner to sellers; not enforced for purchase, wallet or `/start`. The two functions duplicate the check logic.

## I. Scheduler jobs and Redis

- APScheduler `AsyncIOScheduler`: one job `perform_database_backup` every 24 h (`main.py` L98-105); stale comment says "5 minutes". No other jobs. Scheduler is not shut down in `finally`.
- Redis: `redis` in `requirements.txt` and a `redis` service in `docker-compose.yml`, but NO usage in code.
- Backup writes the zip into the process CWD and contains `servers.password` (plaintext) and `users`; sent to the owner via Telegram.

## J. FSM

Storage: `Dispatcher()` with no argument -> aiogram default `MemoryStorage` (`main.py` L95; no `RedisStorage` anywhere). All FSM data is lost on restart (a customer who already paid but lost state can no longer send the receipt: `process_receipt_photo` requires `transaction_id` in FSM).

StatesGroups (`bot/states.py`): `WalletChargeStates` (amount, receipt), `AdminStates` (card), `UserStates` (support message), `AdminTicketStates` (reply), `AdminCustomerStates` (broadcast, search, wallet amount), `AdminForceJoinStates`, `AddServerStates` (name, url, username, password, vendor selection), `AddPlanStates` (title, volume, days, user_limit, price, description), `EditPlanStates`, `PurchaseStates` (discount code), `AdminDiscountStates` (code, percent), `AdminRedirectStates`, `AdminPartnerStates` (telegram id, name). FSM keys are per user+chat; state handlers have no role re-check.

## K. Contradictions with AGENTS.md

1. `core/database/models` is a single file `core/database/models.py`, not a package.
2. §1 "Backups every 24 h" is true, but a stale comment says 5 minutes.
3. `redis` is in requirements but unused; FSM is `MemoryStorage`.
4. §3 "never float" — models use `Float` for wallet, tx amount and plan price.
5. §3 conditional update / `FOR UPDATE` — none used (all read-then-write).
6. §3 layering handler -> service -> repository — NOT FOUND: logic and queries live in handlers; `core/services` has only the panel client.
7. §3 timeouts on every panel call, per-server TLS flag — none.
8. `.env.example`, `tests/`, pytest config, ruff config: NOT FOUND.
9. `main.py` is at repo root and `bot/main.py` is empty.
10. `requirements.txt` is unpinned (`>=`) and lacks `ruff`, `pytest`, `pytest-asyncio`.

## L. Top-10 risks for tasks 01-03

1. (02) Approve/reject race and double credit/refund: `admin_approve_transaction`, `admin_reject_transaction` read-then-write `tx.status`; Float wallet math.
2. (02/03) Receipt IDOR: `admin_receipt_detail`, `admin_approve_transaction`, `admin_reject_transaction` never verify the actor is a vendor or owns the tx.
3. (02) Receipt erased: `tx.receipt_file_id = None` + message delete (`admin_approve_transaction` L446/L537, reject delete) conflicts with persisted receipts/history.
4. (02) Panel call after `approved` with no retry state: failure sends exception text to the customer, tx stays `approved` with no subscription.
5. (01) Hard-coded `group_ids`: `admin_handlers.py` L476, `user_handlers.py` L777 and L1724, keyed on a literal panel username.
6. (01) Single "Marzban"-named client using `group_ids`, no panel type, no timeouts, no TLS option; `servers.password` plaintext (also in backups); panel username not stored.
7. (03) Missing authorization: `toggle_server_status`, `delete_server`, `admin_show_ticket`, `admin_reply_ticket_*`, `admin_close_ticket`, `admin_force_join_delete`, `start_add_server` (selective only hidden in UI), `process_partner_*`, `free_test_generate`, `process_wallet_buy` (client-supplied discount id).
8. (03) Implicit roles (`vendors` row + `OWNER_ID`), `is_active` not enforced for panel access; no owner-level broadcast or forced-join inheritance.
9. (03) Broadcast inline, text-only, catches only `TelegramBadRequest`; user text sent as HTML.
10. (all) `MemoryStorage` FSM, no tests/CI config, one Alembic revision, `DatabaseMiddleware` never commits/rolls back (e.g. `process_receipt_photo` deducts wallet before Telegram send).

## M. Owner answers (from the discovery review)

- Panel support target: three panel types behind one web-service layer — Marzban, PasarGuard, Hiddify — chosen by the admin when registering a server.
- `group_ids` are provider-side panel settings: a subscription gets certain configs only if the right group ids are sent at creation. They must be discovered from the panel, not hard-coded.
- "Seller" and "admin" are the same role (a `vendors` row).
- The double redirect hop in `process_receipt_photo` (section F) is not a priority; verify only if needed in task 02.
