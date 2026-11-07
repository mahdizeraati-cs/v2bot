# Marzban reference

Sources:
- Source/docs: https://github.com/Gozargah/Marzban
- Interactive OpenAPI on a running panel: `https://<panel>/docs` (FastAPI default) — **VERIFY the path on the real panel**.

## Verified facts (consistent across several client libraries and samples)
- Auth: `POST /api/admin/token` with form-encoded `username` + `password` → JSON with `access_token`; send `Authorization: Bearer <token>`.
- Create user: `POST /api/user` with JSON fields:
  `username`, `proxies` (map protocol → settings, e.g. `{"vless": {"flow": ""}, "vmess": {}}`), `inbounds` (map protocol → list of inbound **tags**),
  `expire` (unix timestamp; `0`/null = never), `data_limit` (bytes; `0` = unlimited), `data_limit_reset_strategy` (e.g. `no_reset`),
  `status` (`active`/`disabled`; `on_hold` also exists with `on_hold_timeout` / `on_hold_expire_duration`), `note`.
- User response includes `subscription_url`, `links`, `used_traffic`, `lifetime_used_traffic`, `status`, `excluded_inbounds`.
- Other user calls: get / modify (`PUT`) / delete by username; reset usage; revoke subscription.
- Inbounds discovery: system/inbounds endpoint (`GET /api/inbounds`) returns available inbounds grouped by protocol.
- There is **no "group" concept** in this API: access = `proxies` (protocols) + `inbounds` (tags).

## VERIFY
- Exact path/shape of `GET /api/inbounds` and whether an omitted `inbounds` means "all inbounds of the given protocols" (do not rely on it; fill explicitly).
- Username rules (commonly 3–32 chars, letters/digits/underscore) — enforce in the username generator.
- Whether `subscription_url` is absolute or a relative `/sub/<token>` (prefix the panel's public sub-domain if relative; make it configurable via `panel_config["sub_url_template"]`).
- How `extend` should behave when `expire` is already in the past (start from now) and when the user is `expired`/`limited` (set `status` back to `active`).
- Reset/renew semantics: `data_limit` is a total — extending traffic means `old_limit + add_bytes`, not `add_bytes`.

## Targets mapping
`list_targets()` → one `Target(remote_id=<tag>, name=<tag>)` per inbound, with the protocol kept in an adapter-private field.
Provisioning builds `proxies` from the protocols present and `inbounds` from the selected (default: all) tags.
