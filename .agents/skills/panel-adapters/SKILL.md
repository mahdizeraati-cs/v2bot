---
name: panel-adapters
description: Playbook for the V2Ray panel integration layer — PasarGuard, Marzban and Hiddify adapters, per-panel authentication, user/subscription lifecycle (create, renew, disable, delete, usage), dynamic group/inbound discovery instead of hard-coded group IDs, and the panel-type-aware "register server" admin flow. Use this skill whenever a task touches panel API calls, server registration or editing, subscription creation/renewal/disable/delete, group_ids or inbounds, "subscription failed on one server", or adding support for another panel — even if the request only says "fix server registration" or "sub creation broke after the provider changed something".
disable-model-invocation: false

---

# Panel adapters

## Why this exists

1. The bot only speaks PasarGuard. Owners also run Marzban and Hiddify, so the panel layer must be pluggable.
2. PasarGuard `group_ids` were hard-coded as a numeric array. When a provider re-numbered groups, one server silently
   assigned users to the wrong group (or none). Group IDs are **data owned by the panel**, so the bot must ask the panel
   what exists instead of remembering numbers.

## Ground rules

- **Verify before coding.** For each panel, fetch the official source listed in `references/<panel>.md` (use the `fetch` tool)
  and write the endpoints, auth, payload and one sample response you rely on into `docs/panels.md` with the source URL.
  Facts marked **VERIFY** in the references come from secondary sources (client libraries) — confirm them against the
  panel's own OpenAPI (`/docs` or Swagger) or official docs. If you cannot reach a source, stop and tell the owner;
  do not code from memory.
- **Preserve the working PasarGuard behaviour.** The existing layer works in production. Refactor it behind the adapter
  without changing payload shape, then change group handling as a separate, reviewable step.
- **One HTTP stack.** Reuse the HTTP client the repo already uses for panels (likely `aiohttp`). No third-party panel SDKs.

## Adapter contract

Place it where the repo's layout suggests (suggested: `core/panels/`). Adapt names to the codebase, keep the shape.

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol


class PanelType(str, Enum):
    PASARGUARD = "pasarguard"
    MARZBAN = "marzban"
    HIDDIFY = "hiddify"


@dataclass(frozen=True)
class CredentialField:
    key: str  # "base_url", "username", "password", "admin_proxy_path", ...
    prompt_fa: str  # shown to the admin
    secret: bool = False  # the admin's message is deleted right after it is read
    validator: str | None = None


@dataclass(frozen=True)
class Target:  # PasarGuard "group", Marzban "inbound"
    remote_id: str
    name: str
    enabled: bool = True


@dataclass(frozen=True)
class UserSpec:
    username: str
    data_limit_bytes: int  # 0 = unlimited
    duration_days: int  # 0 = unlimited; the adapter converts to the panel's own format
    note: str = ""


@dataclass(frozen=True)
class RemoteUser:
    remote_id: str  # username (PasarGuard/Marzban) or uuid (Hiddify)
    username: str
    subscription_url: str  # always absolute
    status: str  # normalised: active|disabled|limited|expired|on_hold
    used_bytes: int
    data_limit_bytes: int
    expire_at: datetime | None


class PanelAdapter(Protocol):
    panel_type: PanelType
    supports_targets: bool  # False for Hiddify

    def credential_schema(self) -> list[CredentialField]: ...
    async def ping(self) -> None: ...  # auth + cheap call; raises PanelError subclasses
    async def list_targets(self) -> list[Target]: ...
    async def create_user(self, spec: UserSpec) -> RemoteUser: ...
    async def get_user(self, remote_id: str) -> RemoteUser | None: ...
    async def extend_user(self, remote_id: str, add_days: int, add_bytes: int) -> RemoteUser: ...
    async def set_enabled(self, remote_id: str, enabled: bool) -> RemoteUser: ...
    async def delete_user(self, remote_id: str) -> None: ...
```

Errors (all inherit `PanelError`): `PanelAuthError`, `PanelUnreachable` (timeouts/5xx — retryable),
`PanelRejected` (4xx — carries the panel's message, not retryable), `PanelConfigError` (e.g. no assignable groups),
`PanelCapabilityError`. Handlers translate these to Persian messages; they never see raw HTTP errors.

`get_adapter(server) -> PanelAdapter` is a factory keyed by `server.panel_type`. Legacy rows default to `pasarguard`.

## Data model (propose in the plan; migrate through Alembic)

- `servers.panel_type` — `String(16) NOT NULL server_default 'pasarguard'` (a CHECK constraint is safer than a native PG enum).
- `servers.panel_config` — `JSONB NULL` for type-specific extras: `verify_ssl`, `admin_proxy_path`, `client_proxy_path`,
  `group_mode` (`all`|`selected`), `selected_targets` (`[{"id": "3", "name": "Premium"}]`), `sub_url_template`.
- Keep the existing credential columns working. Do not move or rename them in this task.

## Capability matrix (details in references)

| | PasarGuard | Marzban | Hiddify |
|---|---|---|---|
| Auth | admin token (login) | admin token (login, form-encoded) | `Hiddify-API-Key` header = admin UUID |
| User key | username | username | uuid |
| "Targets" | **groups** (`group_ids`) | inbounds per protocol (`inbounds`, `proxies`) | none |
| Quota unit | bytes | bytes | GB (float) |
| Duration | `expire` | `expire` (unix ts, 0 = never) | `package_days` + `start_date` |

## Group resolution (PasarGuard) — the core fix

Default `group_mode = "all"`: send **every enabled group the bot's panel-admin can see**, fetched live.
`"selected"` is an opt-in mode for servers where some groups must not be handed to customers.

```python
async def resolve_group_ids(server, adapter) -> list[int]:
    groups = await get_cached_targets(server, adapter)  # TTL 60–300 s; refresh once on any mismatch
    enabled = [g for g in groups if g.enabled]
    cfg = server.panel_config or {}
    if cfg.get("group_mode", "all") == "all":
        ids = [int(g.remote_id) for g in enabled]
    else:
        ids, problems = [], []
        for sel in cfg.get("selected_targets", []):
            exact = next(
                (g for g in enabled if g.remote_id == str(sel["id"]) and g.name == sel["name"]), None
            )
            by_name = next((g for g in enabled if g.name == sel["name"]), None)
            if exact:
                ids.append(int(exact.remote_id))
            elif by_name:
                ids.append(int(by_name.remote_id))
                problems.append(("renumbered", sel, by_name))  # persist new id
            else:
                problems.append(("missing_or_id_reused", sel, None))  # id-only match is NOT trusted
        await alert_server_admins_if(problems)
    if not ids:
        raise PanelConfigError("no assignable groups")  # never create a user with zero groups
    return ids
```

Why an ID-only match is not trusted: that is exactly the failure we are fixing — the provider re-used a number for a different group.
A name match with a different ID is a re-numbering and is safe to follow.

For Marzban the equivalent is `list_targets()` → `GET /api/inbounds`; fill `inbounds` per protocol explicitly (deterministic) rather
than relying on the panel's default. Hiddify: `supports_targets = False`, `list_targets()` returns `[]`.

## Admin flow: register / edit a server

Order matters: the credential fields differ per panel, so **ask the panel type first**.

1. Inline keyboard: PasarGuard / Marzban / Hiddify (+ cancel).
2. For each `credential_schema()` field: prompt → validate format → store in FSM. `secret=True` fields: delete the admin's message after reading it.
3. `ping()` with a "در حال بررسی اتصال…" status; on `PanelAuthError` / `PanelUnreachable` show a specific Persian reason and offer retry / edit field / cancel.
4. If `supports_targets`: `list_targets()` → show them; default choice "همه‌ی گروه‌ها (پیشنهادی)", alternative "انتخاب دستی" (toggle buttons, max 8 per row-page).
5. Summary screen (secrets masked) → confirm → save (`panel_type`, credentials, `panel_config`).
6. Edit-server screen gets: «نوع پنل», «تست اتصال», «بازخوانی گروه‌ها / اینباندها», «حالت گروه (همه/انتخابی)». Legacy servers show `pasarguard`.

FSM state must survive restarts if Redis storage is already wired for FSM; if it is not, say so in the report instead of silently changing storage.

## Provisioning safety

- Deterministic usernames derived from the order (e.g. `{prefix}{user_id}_{order_id}`) and conforming to each panel's username rules
  (**VERIFY** per panel). Before `create_user`, `get_user` — a retry after a timeout must find the user, not create a duplicate.
- Order state: `pending` → (panel call) → `fulfilled` | `failed_retryable`. Never hold a DB transaction across the panel call.
- Token cache per server with expiry; re-auth once on 401 under an `asyncio.Lock`. Timeouts: connect 5 s, total 20 s.
  Retry only idempotent calls (GET, or create-after-lookup) with exponential backoff, max 3.
- `subscription_url` from some panels may be relative or use a different public domain: normalise to an absolute URL in the adapter.
- Never log tokens, passwords, API keys, or full subscription URLs.

## Tests

- A shared contract-test suite parametrised over all adapters (mocked HTTP): create → get → extend → disable → enable → delete,
  plus 401-then-reauth, timeout → `PanelUnreachable`, 4xx → `PanelRejected`.
- Group resolution: all / selected / renumbered / id-reused / empty list / disabled group / listing failure.
- Registration flow: happy path, wrong password, unreachable host, cancel mid-way, secret message deleted.

## Pitfalls checklist

- Sending `group_ids` that the bot's panel-admin may not use → panel rejects (PasarGuard validates admin's allowed groups). Use only IDs from the live listing.
- Treating Hiddify GB as bytes (or vice versa). Convert in exactly one place.
- Forgetting that a Hiddify "extend" is `package_days`/`start_date` logic, not an absolute `expire` timestamp.
- Timezones: store UTC, convert in the adapter.
- `verify_ssl=False` as a global default. It must be per-server and off only when the owner sets it.

References: `references/pasarguard.md`, `references/marzban.md`, `references/hiddify.md` — read only the one you are working on.
