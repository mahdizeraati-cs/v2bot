"""کلاینت HTTP مشترک برای پنل‌ها: timeout، TLS، نگاشت خطا، retry فقط برای GET."""

from __future__ import annotations

import asyncio
import json as jsonlib
import logging
from typing import Any

import aiohttp

from core.panels.base import PanelAuthError, PanelRejected, PanelUnreachable

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5
TOTAL_TIMEOUT = 20
USER_AGENT = "V2RayBot/1.0"


def _extract_message(body: Any, text: str) -> str:
    """پیام خطای خود پنل (کوتاه‌شده). پاسخ پنل شامل راز ما نیست، ولی طول را محدود می‌کنیم."""
    msg = ""
    if isinstance(body, dict):
        detail = body.get("detail", body.get("msg", body.get("message")))
        if isinstance(detail, str):
            msg = detail
        elif isinstance(detail, list) and detail:
            first = detail[0]
            msg = str(first.get("msg", first)) if isinstance(first, dict) else str(first)
        elif detail is not None:
            msg = str(detail)
    if not msg:
        msg = text
    return msg.strip().replace("\n", " ")[:200]


class PanelHTTP:
    def __init__(
        self,
        base_url: str,
        *,
        verify_ssl: bool = True,
        headers: dict[str, str] | None = None,
        connect_timeout: float = CONNECT_TIMEOUT,
        total_timeout: float = TOTAL_TIMEOUT,
        backoff_base: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self._headers = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
        self._timeout = aiohttp.ClientTimeout(total=total_timeout, connect=connect_timeout)
        self._backoff_base = backoff_base
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=None if self.verify_ssl else False)
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                connector=connector,
                headers=self._headers,
                trust_env=True,
            )
        return self._session

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        retries: int | None = None,
    ) -> Any:
        """JSON پاسخ را برمی‌گرداند (یا None برای بدنه‌ی خالی).

        401 و ریدایرکت -> PanelAuthError؛ سایر 4xx -> PanelRejected؛ 5xx/شبکه/timeout -> PanelUnreachable.
        فقط GET به‌صورت پیش‌فرض retry می‌شود (idempotent).
        """
        if retries is None:
            retries = 2 if method.upper() == "GET" else 0
        last: PanelUnreachable | None = None
        for attempt in range(retries + 1):
            try:
                return await self._once(method, path, json=json, data=data, headers=headers)
            except PanelUnreachable as exc:
                last = exc
                if attempt < retries:
                    await asyncio.sleep(self._backoff_base * (2**attempt))
        assert last is not None
        raise last

    async def _once(
        self, method: str, path: str, *, json: Any, data: Any, headers: dict[str, str] | None
    ) -> Any:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        try:
            async with session.request(
                method, url, json=json, data=data, headers=headers, allow_redirects=False
            ) as resp:
                status = resp.status
                text = await resp.text()
                body: Any = None
                if text:
                    try:
                        body = jsonlib.loads(text)
                    except ValueError:
                        body = None
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            # فقط نوع خطا لاگ می‌شود؛ URL ممکن است حاوی مسیر محرمانه‌ی ادمین (Hiddify) باشد.
            logger.warning("panel request failed: %s", type(exc).__name__)
            raise PanelUnreachable(type(exc).__name__) from exc

        if 300 <= status < 400 or status == 401:
            raise PanelAuthError("unauthorized", status=status)
        if status >= 500:
            raise PanelUnreachable(f"HTTP {status}", status=status)
        if status >= 400:
            raise PanelRejected(_extract_message(body, text), status=status)
        return body
