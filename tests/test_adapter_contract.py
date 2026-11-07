"""تست قرارداد مشترک برای هر سه آداپتور (با پنل جعلی؛ بدون شبکه‌ی واقعی)."""

from __future__ import annotations

import logging
from datetime import timedelta

import pytest

from core.panels import (
    PanelAuthError,
    PanelRejected,
    PanelUnreachable,
    UserSpec,
)
from core.panels.common import GB
from tests.conftest import SECRETS

SPEC = UserSpec(username="U_123_45_1700000000", data_limit_bytes=5 * GB, duration_days=30, note="t")


async def test_full_lifecycle(panel):
    a = panel.adapter
    await a.ping()

    created = await a.create_user(SPEC)
    rid = a.remote_id_for(SPEC.username)
    assert created.remote_id == rid
    assert created.subscription_url.startswith("http")  # همیشه absolute
    assert created.status == "active"
    assert created.data_limit_bytes == 5 * GB
    assert created.expire_at is not None

    before = await a.get_user(rid)
    assert before is not None

    after = await a.extend_user(rid, add_days=10, add_bytes=GB)
    assert after.data_limit_bytes == 6 * GB
    assert after.expire_at - before.expire_at == timedelta(days=10)

    assert (await a.set_enabled(rid, False)).status == "disabled"
    assert (await a.set_enabled(rid, True)).status == "active"

    await a.delete_user(rid)
    assert await a.get_user(rid) is None
    await a.delete_user(rid)  # حذف دوباره خطا نمی‌دهد


async def test_create_is_idempotent(panel):
    first = await panel.adapter.create_user(SPEC)
    second = await panel.adapter.create_user(SPEC)
    assert first.remote_id == second.remote_id
    assert len(panel.fake.created_payloads) == 1


async def test_get_unknown_user_returns_none(panel):
    assert await panel.adapter.get_user(panel.adapter.remote_id_for("nobody")) is None


async def test_wrong_credentials_raise_auth_error(bad_panel):
    with pytest.raises(PanelAuthError):
        await bad_panel.adapter.ping()


async def test_timeout_maps_to_unreachable_and_no_secret_in_logs(panel, caplog):
    panel.fake.slow = True
    caplog.set_level(logging.DEBUG)
    with pytest.raises(PanelUnreachable):
        await panel.adapter.create_user(SPEC)
    for secret in SECRETS:
        assert secret not in caplog.text


async def test_4xx_maps_to_rejected(panel):
    panel.fake.reject_create = True
    with pytest.raises(PanelRejected) as info:
        await panel.adapter.create_user(SPEC)
    assert info.value.status in (400, 422)


async def test_retry_after_timeout_does_not_duplicate(panel):
    """POST کند timeout می‌شود ولی کاربر ساخته شده؛ تلاش مجدد باید همان را پیدا کند."""
    panel.fake.slow = True
    with pytest.raises(PanelUnreachable):
        await panel.adapter.create_user(SPEC)
    panel.fake.slow = False
    result = await panel.adapter.create_user(SPEC)
    assert result.username in (SPEC.username,)
    assert len({p.get("username") or p.get("name") for p in panel.fake.created_payloads}) == 1


async def test_reauth_once_after_401(panel):
    if panel.kind == "hiddify":
        pytest.skip("Hiddify توکن ندارد (کلید ثابت در هدر)")
    a = panel.adapter
    await a.get_user("x")
    assert panel.fake.logins == 1
    panel.fake.expire_tokens()
    await a.get_user("x")
    assert panel.fake.logins == 2
