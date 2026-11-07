# PasarGuard reference

Sources (fetch these; the panel's own `/docs` OpenAPI of the target server is authoritative):
- Docs (groups concept): https://docs.pasarguard.org/zh/panel/groups/
- Source: https://github.com/PasarGuard/panel
- Secondary (API map, may lag): https://deepwiki.com/PasarGuard/panel/9-api-reference

## Verified facts
- A **group** is the access-control unit: user → groups → inbound tags → hosts. Groups reference inbounds by **tag**, not by ID.
- User↔group is many-to-many. A user reaches the union of inbounds of its **enabled** groups; a group has `is_disabled`.
- `GET /api/groups` lists groups. Creating/modifying/deleting groups is **sudo-only** — the bot only needs read.
- User create/modify accepts `group_ids` (list of ints). Python-client sample: `UserCreate(username, data_limit=<bytes>, expire=..., status=ACTIVE, group_ids=[1], note=...)`;
  the created user exposes `id`, `username`, `subscription_url`.
- Non-sudo panel admins can be restricted with `allowed_group_ids`; the group listing and user create/modify validation respect it
  (PasarGuard/panel PR #755). Therefore: **only send IDs returned by the live listing, fetched with the bot's own credentials.**
- User endpoints (from the API map): `GET /api/users` (filters incl. `group_ids`, `load_sub`), `GET /api/user/{username}`,
  `POST /api/user/{username}/revoke_sub`, `GET /api/user/{username}/usage`; update and delete by username.
- Bulk actions exist (e.g. bulk disable) — not needed for v1.

## VERIFY on the real panel / OpenAPI before coding
- Token endpoint and format (Marzban lineage: `POST /api/admin/token`, form-encoded `username`/`password`, response `access_token`, header `Authorization: Bearer …`).
- `expire` format: unix timestamp vs ISO-8601 datetime vs null for "never" — differs by version. **Copy whatever the existing bot code already sends.**
- Status enum values (`active`, `disabled`, `on_hold`, `limited`, `expired`?) and how to disable/enable a user (`status` via modify?).
- Response envelope of `GET /api/groups` (list vs `{"groups": [...], "total": n}`) and field names (`id`, `name`, `inbound_tags`, `is_disabled`).
- Whether `subscription_url` is absolute.

## Existing behaviour to preserve
The current bot already creates PasarGuard users. Find that code (grep for `group_ids`), record its exact request/response shape in
`docs/panels.md`, and make `PasarGuardAdapter` reproduce it byte-for-byte except for the group source.
