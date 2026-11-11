from __future__ import annotations



from typing import Any
from urllib.parse import quote

from core.panels import groups
from core.panels.base import (
    CredentialField,
    PanelRejected,
    PanelType,
    RemoteUser,
    Target,
    UserSpec,
)
from core.panels.common import absolute_url, parse_expire, encode_data_limit, encode_expire, encode_user_limit
from core.panels.token_base import TokenPanel

_PROXY_SETTINGS = {
    "vmess": {},
    "vless": {},
    "trojan": {},
    "shadowsocks": {"method": "aes-256-gcm"},
}


class PasarGuardAdapter(TokenPanel):
    panel_type = PanelType.PASARGUARD
    supports_targets = True

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

    # ---------------------------------------------------------- discovery
    async def ping(self) -> None:
        await self._token(force=True)
        await self.list_targets()

    async def list_targets(self) -> list[Target]:
        try:
            body = await self._api("GET", "/api/groups")
            rows = (body or {}).get("groups", [])
            return [
                Target(str(g["id"]), str(g.get("name", g["id"])), enabled=not g.get("is_disabled", False))
                for g in rows
            ]
        except PanelRejected as exc:
            if exc.status != 403:
                raise
        # ادمین بدون groups.read: فهرست سبک (بدون وضعیت غیرفعال)
        body = await self._api("GET", "/api/groups/simple")
        return [Target(str(g["id"]), str(g.get("name", g["id"]))) for g in (body or {}).get("groups", [])]

    # ------------------------------------------------------------ users
    def _create_payload(self, spec: UserSpec, group_ids: list[int], now: float) -> dict[str, Any]:
        # ترتیب و شکل کلیدها عیناً مثل MarzbanClient.create_user قدیمی است (به‌جز group_ids).
        expire_val = encode_expire("pasarguard", spec.duration_days, now)
        data_limit_val = encode_data_limit("pasarguard", spec.data_limit_bytes)
        hwid_limit_val = encode_user_limit("pasarguard", spec.hwid_limit)
        
        payload: dict[str, Any] = {
            "username": spec.username,
            "status": "active",
            "data_limit": data_limit_val,
            "note": spec.note,
            "group_ids": group_ids,
            "proxy_settings": _PROXY_SETTINGS,
            "data_limit_reset_strategy": "no_reset",
        }
        if expire_val is not None:
            payload["expire"] = str(expire_val)
        # U1c: PasarGuard unlimited user count is explicit hwid_limit: null
        payload["hwid_limit"] = hwid_limit_val
        return payload

    async def create_user(self, spec: UserSpec) -> RemoteUser:
        existing = await self.get_user(spec.username)
        if existing:
            return existing
        group_ids = await groups.resolve_group_ids(self)
        payload = self._create_payload(spec, group_ids, self._clock())
        try:
            body = await self._api("POST", "/api/user", json=payload, retries=0)
        except PanelRejected as exc:
            if exc.status == 409:
                found = await self.get_user(spec.username)
                if found:
                    return found
            # شاید گروه‌ها بین کش و ساخت عوض شده‌اند: یک‌بار تازه بخوان و فقط اگر فرق کرد تکرار کن.
            groups.invalidate_targets(self.cache_key)
            fresh = await groups.resolve_group_ids(self, force=True)
            if fresh == group_ids:
                raise
            payload = self._create_payload(spec, fresh, self._clock())
            body = await self._api("POST", "/api/user", json=payload, retries=0)
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
        now = self._clock()
        payload: dict[str, Any] = {}
        if add_days > 0 and current.expire_at is not None:
            base = max(now, current.expire_at.timestamp())
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

    # ---------------------------------------------------------- mapping
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
