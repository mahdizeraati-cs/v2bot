"""کشف زنده‌ی گروه‌های PasarGuard.

تصمیم مالک: همیشه «همه‌ی گروه‌های فعالِ» همان سرور به کاربر داده می‌شود؛ حالت انتخابی وجود ندارد.
شناسه‌ها هرگز در کد/دیتابیس ثابت نگه داشته نمی‌شوند و در لحظه‌ی ساخت کاربر از خود پنل خوانده می‌شوند.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Protocol

from core.panels.base import PanelConfigError, Target

logger = logging.getLogger(__name__)

TARGETS_TTL_SECONDS = 120

_clock: Callable[[], float] = time.monotonic
_CACHE: dict[str, tuple[float, list[Target]]] = {}


class _HasTargets(Protocol):
    cache_key: str

    async def list_targets(self) -> list[Target]: ...


def clear_targets_cache() -> None:
    _CACHE.clear()


def invalidate_targets(cache_key: str) -> None:
    _CACHE.pop(cache_key, None)


async def get_cached_targets(adapter: _HasTargets, *, force: bool = False) -> list[Target]:
    cached = _CACHE.get(adapter.cache_key)
    if not force and cached and cached[0] > _clock():
        return cached[1]
    targets = await adapter.list_targets()
    previous = {t.remote_id for t in cached[1]} if cached else None
    current = {t.remote_id for t in targets if t.enabled}
    if previous is not None and previous != current:
        logger.warning("panel target set changed (%d -> %d enabled)", len(previous), len(current))
    _CACHE[adapter.cache_key] = (_clock() + TARGETS_TTL_SECONDS, targets)
    return targets


async def resolve_group_ids(adapter: _HasTargets, *, force: bool = False) -> list[int]:
    """شناسه‌ی همه‌ی گروه‌های فعال؛ اگر هیچ نبود، هرگز کاربر بدون گروه ساخته نمی‌شود."""
    targets = await get_cached_targets(adapter, force=force)
    ids = sorted(int(t.remote_id) for t in targets if t.enabled)
    if not ids:
        raise PanelConfigError("هیچ گروه فعالی در پنل پیدا نشد؛ ابتدا در پنل یک گروه فعال بسازید.")
    return ids
