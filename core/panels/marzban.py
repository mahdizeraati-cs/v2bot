"""آداپتور Marzban: دسترسی با proxies + inbounds (بدون مفهوم گروه)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from core.panels.base import (
    CredentialField,
    PanelConfigError,
    PanelRejected,
    PanelType,
    RemoteUser,
    Target,
    UserSpec,
)
from core.panels.common import absolute_url, parse_expire, encode_data_limit, encode_expire
from core.panels.token_base import TokenPanel

# منبع: app/models/user.py در مخزن رسمی Marzban
_USERNAME_RE = re.compile(r"^(?=\w{3,32}\b)[a-zA-Z0-9-_@.]+(?:_[a-zA-Z0-9-_@.]+)*$")


class MarzbanAdapter(TokenPanel):
    panel_type = PanelType.MARZBAN
    supports_targets = True  # inbounds

    def credential_schema(self) -> list[CredentialField]:
        return [
            CredentialField(
                "base_url",
                "🌐 <b>آدرس پنل</b> را وارد کنید (مثال: https://panel.example.com:8000):",
                validator="url",
            ),
            CredentialField("username", "👤 <b>نام کاربری</b> ادمین پنل:", validator="nonempty"),
            CredentialField("password", "🔑 <b>رمز عبور</b> ادمین پنل:", secret=True, validator="nonempty"),
        ]

    def remote_id_for(self, username: str) -> str:
        return username

    async def ping(self) -> None:
        await self._token(force=True)
        await self.list_targets()

    async def list_targets(self) -> list[Target]:
        body = await self._api("GET", "/api/inbounds")
        targets: list[Target] = []
        for protocol, rows in (body or {}).items():
            for row in rows or []:
                tag = str(row.get("tag", ""))
                if tag:
                    targets.append(Target(tag, tag, enabled=True, protocol=str(protocol)))
        return targets

    async def create_user(self, spec: UserSpec) -> RemoteUser:
        if not _USERNAME_RE.match(spec.username):
            raise PanelConfigError("نام کاربری ساخته‌شده برای مرزبان معتبر نیست (۳ تا ۳۲ کاراکتر).")
        existing = await self.get_user(spec.username)
        if existing:
            return existing
        inbounds: dict[str, list[str]] = {}
        for t in await self.list_targets():
            if t.protocol:
                inbounds.setdefault(t.protocol, []).append(t.remote_id)
        if not inbounds:
            raise PanelConfigError("هیچ اینباندی در پنل مرزبان فعال نیست.")
        now = self._clock()
        expire_val = encode_expire("marzban", spec.duration_days, now)
        data_limit_val = encode_data_limit("marzban", spec.data_limit_bytes)
        payload = {
            "username": spec.username,
            "status": "active",
            "proxies": {proto: {} for proto in inbounds},
            "inbounds": inbounds,
            "expire": expire_val,
            "data_limit": data_limit_val,
            "data_limit_reset_strategy": "no_reset",
            "note": spec.note,
        }
        try:
            body = await self._api("POST", "/api/user", json=payload, retries=0)
        except PanelRejected as exc:
            if exc.status == 409:
                found = await self.get_user(spec.username)
                if found:
                    return found
            raise
        return self._to_remote(body)

    async def get_user(self, remote_id: str) -> RemoteUser | None:
        try:
            body = await self._api("GET", f"/api/user/{quote(remote_id, safe='')}")
        except PanelRejected as exc:
            if exc.status == 404:
                return None
            raise
        return self._to_remote(body)

    async def extend_user(self, remote_id: str, add_days: int, add_bytes: int) -> RemoteUser:
        current = await self.get_user(remote_id)
        if current is None:
            raise PanelRejected("کاربر در پنل پیدا نشد.", status=404)
        payload: dict[str, Any] = {}
        if add_days > 0 and current.expire_at is not None:
            base = max(self._clock(), current.expire_at.timestamp())
            payload["expire"] = int(base) + add_days * 86400
        if add_bytes > 0 and current.data_limit_bytes > 0:
            payload["data_limit"] = current.data_limit_bytes + add_bytes
        if current.status in ("expired", "limited"):
            payload["status"] = "active"
        body = await self._api("PUT", f"/api/user/{quote(remote_id, safe='')}", json=payload, retries=0)
        return self._to_remote(body)

    async def set_enabled(self, remote_id: str, enabled: bool) -> RemoteUser:
        body = await self._api(
            "PUT",
            f"/api/user/{quote(remote_id, safe='')}",
            json={"status": "active" if enabled else "disabled"},
            retries=0,
        )
        return self._to_remote(body)

    async def delete_user(self, remote_id: str) -> None:
        try:
            await self._api("DELETE", f"/api/user/{quote(remote_id, safe='')}", retries=0)
        except PanelRejected as exc:
            if exc.status != 404:
                raise

    def _to_remote(self, body: dict[str, Any]) -> RemoteUser:
        username = str(body.get("username", ""))
        hwid_limit = body.get("hwid_limit")
        if hwid_limit is None:
            hwid_limit = 0
        return RemoteUser(
            remote_id=username,
            username=username,
            subscription_url=absolute_url(str(body.get("subscription_url") or ""), self.base_url),
            status=str(body.get("status") or "active").lower(),
            used_bytes=int(body.get("used_traffic") or 0),
            data_limit_bytes=int(body.get("data_limit") or 0),
            expire_at=parse_expire(body.get("expire")),
            hwid_limit=int(hwid_limit),
        )