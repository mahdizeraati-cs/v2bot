"""پایه‌ی مشترک PasarGuard و Marzban: توکن ادمین با login فرم‌انکد."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from core.panels.base import PanelAuthError, PanelRejected
from core.panels.http import PanelHTTP

TOKEN_TTL_SECONDS = 600

# کش توکن به‌ازای هر سرور (کلید: cache_key). با انقضا؛ هرگز لاگ نمی‌شود.
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_LOCKS: dict[str, asyncio.Lock] = {}


def clear_token_cache() -> None:
    _TOKEN_CACHE.clear()
    _LOCKS.clear()


class TokenPanel:
    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        verify_ssl: bool = True,
        cache_key: str | None = None,
        config: dict[str, Any] | None = None,
        http: PanelHTTP | None = None,
        clock: Callable[[], float] = time.time,
    ):
        self.base_url = base_url.rstrip("/")
        self._username = username
        self._password = password
        self.config = config or {}
        self.cache_key = cache_key or f"{self.base_url}|{username}"
        self._clock = clock
        self.http = http or PanelHTTP(self.base_url, verify_ssl=verify_ssl)

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _token(self, *, force: bool = False) -> str:
        lock = _LOCKS.setdefault(self.cache_key, asyncio.Lock())
        async with lock:
            cached = _TOKEN_CACHE.get(self.cache_key)
            if not force and cached and cached[1] > self._clock():
                return cached[0]
            body = await self.http.request(
                "POST",
                "/api/admin/token",
                data={"grant_type": "password", "username": self._username, "password": self._password},
                retries=0,
            )
            token = body.get("access_token") if isinstance(body, dict) else None
            if not token:
                raise PanelRejected("پاسخ ورود شامل توکن نبود.")
            _TOKEN_CACHE[self.cache_key] = (token, self._clock() + TOKEN_TTL_SECONDS)
            return token

    async def _api(self, method: str, path: str, *, json: Any = None, retries: int | None = None) -> Any:
        """درخواست احراز‌شده؛ روی 401 یک‌بار با توکن تازه تکرار می‌شود."""
        for attempt in (0, 1):
            token = await self._token(force=attempt == 1)
            try:
                return await self.http.request(
                    method,
                    path,
                    json=json,
                    headers={"Authorization": f"Bearer {token}"},
                    retries=retries,
                )
            except PanelAuthError:
                if attempt == 1:
                    raise
        raise PanelAuthError("unauthorized")  # pragma: no cover
