"""آداپتور Hiddify Manager (API v2): کلید API در هدر، حجم به GB، مدت با package_days/start_date.

برخی رفتارها در منابع رسمی تأیید نشده‌اند (نگاه کنید به docs/panels.md، بخش Hiddify):
مقدار sentinel برای «نامحدود»، فرمت لینک اشتراک و تمدید کاربر منقضی باید روی پنل واقعی تست شوند.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from core.panels.base import (
    CredentialField,
    PanelConfigError,
    PanelRejected,
    PanelType,
    RemoteUser,
    Target,
    UserSpec,
)
from core.panels.common import GB
from core.panels.http import PanelHTTP

# Hiddify فیلد «نامحدود» ندارد؛ مقادیر بزرگ مثل کاربر پیش‌فرض خود پنل (۳۰۰۰GB / ۳۶۵۰ روز) استفاده می‌شوند.
UNLIMITED_GB = 100_000.0
UNLIMITED_DAYS = 3650
DEFAULT_SUB_TEMPLATE = "https://{domain}/{client_proxy_path}/{uuid}/"


def _today() -> date:
    return datetime.now(UTC).date()


class HiddifyAdapter:
    panel_type = PanelType.HIDDIFY
    supports_targets = False

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        config: dict[str, Any] | None = None,
        verify_ssl: bool = True,
        cache_key: str | None = None,
        seed: str | None = None,
        http: PanelHTTP | None = None,
        clock: Callable[[], float] = time.time,
        today: Callable[[], date] = _today,
    ):
        self.base_url = base_url.rstrip("/")
        self.config = config or {}
        admin_path = str(self.config.get("admin_proxy_path", "")).strip("/")
        if not admin_path:
            raise PanelConfigError("مسیر پروکسی ادمین (admin proxy path) تنظیم نشده است.")
        self._api_prefix = f"/{admin_path}/api/v2"
        self.cache_key = cache_key or f"{self.base_url}|hiddify"
        self._seed = seed or self.base_url
        self._clock = clock
        self._today = today
        self.http = http or PanelHTTP(
            self.base_url, verify_ssl=verify_ssl, headers={"Hiddify-API-Key": api_key}
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    def credential_schema(self) -> list[CredentialField]:
        return [
            CredentialField(
                "base_url",
                "🌐 <b>آدرس پنل</b> (فقط دامین، مثال: https://hiddify.example.com):",
                validator="url",
            ),
            CredentialField(
                "admin_proxy_path",
                "🛡 <b>مسیر پروکسی ادمین</b> (Admin Proxy Path از تنظیمات پیشرفته‌ی پنل):",
                validator="path",
            ),
            CredentialField("api_key", "🔑 <b>کلید API</b> (UUID ادمین):", secret=True, validator="nonempty"),
            CredentialField(
                "client_proxy_path",
                "👥 <b>مسیر پروکسی کاربر</b> (Client Proxy Path، برای ساخت لینک اشتراک):",
                validator="path",
            ),
        ]

    def remote_id_for(self, username: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"v2bot:{self._seed}:{username}"))

    # -------------------------------------------------------------- api
    async def _api(self, method: str, path: str, *, json: Any = None, retries: int | None = None) -> Any:
        return await self.http.request(method, f"{self._api_prefix}{path}", json=json, retries=retries)

    async def ping(self) -> None:
        try:
            await self._api("GET", "/panel/ping/", retries=0)
        except PanelRejected as exc:
            if exc.status != 404:
                raise
            # نسخه‌های دیگر فقط /panel/info/ دارند
            await self._api("GET", "/panel/info/", retries=0)

    async def list_targets(self) -> list[Target]:
        return []

    async def _get_raw(self, remote_id: str) -> dict[str, Any] | None:
        try:
            body = await self._api("GET", f"/admin/user/{quote(remote_id, safe='')}/")
        except PanelRejected as exc:
            if exc.status == 404:
                return None
            raise
        return body

    async def create_user(self, spec: UserSpec) -> RemoteUser:
        remote_id = self.remote_id_for(spec.username)
        existing = await self._get_raw(remote_id)
        if existing:
            return self._to_remote(existing)
        payload = {
            "uuid": remote_id,
            "name": spec.username,
            "usage_limit_GB": spec.data_limit_bytes / GB if spec.data_limit_bytes > 0 else UNLIMITED_GB,
            "package_days": spec.duration_days if spec.duration_days > 0 else UNLIMITED_DAYS,
            "mode": "no_reset",
            "start_date": self._today().isoformat(),
            "enable": True,
            "comment": spec.note,
        }
        try:
            body = await self._api("POST", "/admin/user/", json=payload, retries=0)
        except PanelRejected as exc:
            found = await self._get_raw(remote_id) if exc.status == 400 else None
            if found:
                return self._to_remote(found)
            raise
        return self._to_remote(body)

    async def get_user(self, remote_id: str) -> RemoteUser | None:
        raw = await self._get_raw(remote_id)
        return self._to_remote(raw) if raw else None

    async def extend_user(self, remote_id: str, add_days: int, add_bytes: int) -> RemoteUser:
        raw = await self._get_raw(remote_id)
        if raw is None:
            raise PanelRejected("کاربر در پنل پیدا نشد.", status=404)
        patch: dict[str, Any] = {}
        limit_gb = float(raw.get("usage_limit_GB") or 0)
        if add_bytes > 0 and limit_gb < UNLIMITED_GB:
            patch["usage_limit_GB"] = limit_gb + add_bytes / GB
        days = int(raw.get("package_days") or 0)
        if add_days > 0 and days < UNLIMITED_DAYS:
            if self._is_expired(raw):
                # قانون: اگر منقضی شده، از امروز شروع کن و مصرف را صفر کن.
                patch.update(
                    {"start_date": self._today().isoformat(), "package_days": add_days, "current_usage_GB": 0}
                )
            else:
                patch["package_days"] = days + add_days
        if not patch:
            return self._to_remote(raw)
        body = await self._api("PATCH", f"/admin/user/{quote(remote_id, safe='')}/", json=patch, retries=0)
        return self._to_remote(body)

    async def set_enabled(self, remote_id: str, enabled: bool) -> RemoteUser:
        body = await self._api(
            "PATCH", f"/admin/user/{quote(remote_id, safe='')}/", json={"enable": enabled}, retries=0
        )
        return self._to_remote(body)

    async def delete_user(self, remote_id: str) -> None:
        try:
            await self._api("DELETE", f"/admin/user/{quote(remote_id, safe='')}/", retries=0)
        except PanelRejected as exc:
            if exc.status != 404:
                raise

    # ---------------------------------------------------------- mapping
    def _expire_date(self, raw: dict[str, Any]) -> date | None:
        start = raw.get("start_date")
        days = int(raw.get("package_days") or 0)
        if not start or days >= UNLIMITED_DAYS:
            return None
        try:
            return date.fromisoformat(str(start)[:10]) + timedelta(days=days)
        except ValueError:
            return None

    def _is_expired(self, raw: dict[str, Any]) -> bool:
        end = self._expire_date(raw)
        return end is not None and end < self._today()

    def _subscription_url(self, uid: str) -> str:
        template = str(self.config.get("sub_url_template") or DEFAULT_SUB_TEMPLATE)
        client_path = str(self.config.get("client_proxy_path", "")).strip("/")
        if not client_path and "{client_proxy_path}" in template:
            return ""
        return template.format(
            domain=urlsplit(self.base_url).netloc,
            client_proxy_path=client_path,
            uuid=uid,
        )

    def _to_remote(self, raw: dict[str, Any]) -> RemoteUser:
        uid = str(raw.get("uuid", ""))
        used = int(round(float(raw.get("current_usage_GB") or 0) * GB))
        limit_gb = float(raw.get("usage_limit_GB") or 0)
        limit = 0 if limit_gb >= UNLIMITED_GB else int(round(limit_gb * GB))
        end = self._expire_date(raw)
        if raw.get("enable") is False:
            status = "disabled"
        elif self._is_expired(raw):
            status = "expired"
        elif limit and used >= limit:
            status = "limited"
        else:
            status = "active"
        return RemoteUser(
            remote_id=uid,
            username=str(raw.get("name", "")),
            subscription_url=self._subscription_url(uid),
            status=status,
            used_bytes=used,
            data_limit_bytes=limit,
            expire_at=datetime(end.year, end.month, end.day, tzinfo=UTC) if end else None,
        )
