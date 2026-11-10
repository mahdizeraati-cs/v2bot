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


async def test_unlimited_encoding_request_body(panel):
    """U1a-U1d: unlimited (0) encoded per panel in request body."""
    from core.panels.common import encode_expire, encode_data_limit, encode_user_limit

    spec = UserSpec(
        username=f"U_unlimited_{panel.kind}",
        data_limit_bytes=0,
        duration_days=0,
        hwid_limit=0,
        note="unlimited test",
    )
    await panel.adapter.create_user(spec)

    payload = panel.fake.created_payloads[-1]

    if panel.kind == "pasarguard":
        # PasarGuard: omit expire key entirely for unlimited
        assert "expire" not in payload, f"PasarGuard should omit expire key for unlimited, got {payload.get('expire')}"
        # data_limit: 0 is acceptable (panel treats 0 as unlimited)
        assert payload["data_limit"] == 0
        # U1c: PasarGuard unlimited user count is explicit hwid_limit: null
        assert payload["hwid_limit"] is None
    elif panel.kind == "marzban":
        # Marzban: expire=0 (int) for unlimited
        assert payload["expire"] == 0
        # data_limit: 0 for unlimited
        assert payload["data_limit"] == 0
    elif panel.kind == "hiddify":
        # Hiddify: package_days=UNLIMITED_DAYS (3650), usage_limit_GB=UNLIMITED_GB (100000)
        from core.panels.hiddify import UNLIMITED_DAYS, UNLIMITED_GB
        assert payload["package_days"] == UNLIMITED_DAYS
        assert payload["usage_limit_GB"] == UNLIMITED_GB
        # Note: Hiddify has no hwid_limit equivalent


async def test_unlimited_encoding_reverse_mapping(panel):
    """U1d: panel responses meaning unlimited map back to 0 in RemoteUser."""
    # Create a limited user first, then test get_user with unlimited values
    spec = UserSpec(
        username=f"U_reverse_{panel.kind}",
        data_limit_bytes=5 * 1024**3,
        duration_days=30,
        note="reverse test",
    )
    await panel.adapter.create_user(spec)

    # Manually set fake panel user to unlimited values
    remote_id = panel.adapter.remote_id_for(spec.username)
    fake_user = panel.fake.users[remote_id]

    if panel.kind == "pasarguard":
        fake_user["expire"] = None  # unlimited
        fake_user["data_limit"] = 0  # unlimited
    elif panel.kind == "marzban":
        fake_user["expire"] = None  # unlimited
        fake_user["data_limit"] = 0  # unlimited
    elif panel.kind == "hiddify":
        from core.panels.hiddify import UNLIMITED_DAYS, UNLIMITED_GB
        fake_user["package_days"] = UNLIMITED_DAYS
        fake_user["usage_limit_GB"] = UNLIMITED_GB
        fake_user["current_usage_GB"] = 0.0
        fake_user["start_date"] = "2023-11-14"

    remote = await panel.adapter.get_user(remote_id)
    # All three should map unlimited to 0 for display
    assert remote is not None, f"get_user returned None for {panel.kind}"
    assert remote.data_limit_bytes == 0, f"Expected data_limit_bytes=0 for unlimited, got {remote.data_limit_bytes}"
    assert remote.expire_at is None, f"Expected expire_at=None for unlimited, got {remote.expire_at}"


async def test_negative_values_rejected(panel):
    """U1d: negative values should be rejected."""
    spec = UserSpec(
        username=f"U_negative_{panel.kind}",
        data_limit_bytes=-1,
        duration_days=-1,
        hwid_limit=-1,
    )
    with pytest.raises(ValueError):
        await panel.adapter.create_user(spec)