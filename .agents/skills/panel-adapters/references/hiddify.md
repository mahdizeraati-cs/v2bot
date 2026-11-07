# Hiddify Manager reference

Sources:
- Official API how-to: https://hiddify.com/manager/contribution/How-to-use-API-in-HiddifyManager-project
- Swagger/request builder lives **inside the panel**: Admin Panel → Settings → API. It is the authority for the installed version.

## Verified facts (official how-to)
- Use **API v2** (v1 may be deprecated). The docs warn that endpoints/fields can change between versions → read the panel's own Swagger.
- Auth: header `Hiddify-API-Key: <admin UUID>` (prefer the header over putting the key in the URL).
- Base URLs: `https://<domain>/<admin_proxy_path>/api/v2/panel` (version, ping), `.../api/v2/admin` (current admin, admin CRUD, server stats, logs),
  and `https://<domain>/<user_proxy_path>/api/v2/user/` (user-facing: own info, subscription links, MTProto proxies).
- Admin proxy path is shown in Settings → Advanced Settings → Admin Proxy Path.
- Cheap connectivity check: `GET /<admin_proxy_path>/api/v2/panel/version` with the API-key header.

## Reported by third-party clients — VERIFY in the panel's Swagger
- User object fields: `uuid`, `name`, `usage_limit_GB` (float GB), `package_days`, `mode` (`no_reset|daily|weekly|monthly`),
  `start_date` (`YYYY-MM-DD`), `comment`, `telegram_id`, `enable`, `current_usage_GB`, `last_online`, `added_by_uuid`.
- v2 user endpoints are expected under `/<admin_proxy_path>/api/v2/admin/user/` (list/create) and `.../user/<uuid>/` (get/update/delete). **Confirm.**
- The client-facing subscription link is built from the **client/user proxy path** + user uuid, e.g. `https://<domain>/<client_proxy_path>/<uuid>/`.
  Confirm on a real install; keep it configurable with `panel_config["sub_url_template"]`.

## Credential schema for registration
`base_url` (domain, https), `admin_proxy_path`, `api_key` (admin UUID, **secret**), `client_proxy_path`, `verify_ssl` (default true).

## Semantics to implement carefully
- No groups/inbounds per user → `supports_targets = False`; skip the discovery step in the registration flow.
- Units: GB (float), not bytes — convert in one place.
- Renew/extend = adjust `package_days` / `start_date` (and reset usage if the plan says so); there is no absolute expiry field. Define and test the rule:
  "if still active: add days to the remaining time; if expired: restart from today".
- Disable/enable: `enable` flag.
