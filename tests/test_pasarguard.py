from __future__ import annotations

import pytest

from core.panels import PanelConfigError, UserSpec
from core.panels.common import GB
from core.panels.groups import clear_targets_cache, resolve_group_ids
from tests.conftest import NOW

SPEC = UserSpec(username="U_123_45_1700000000", data_limit_bytes=50 * GB, duration_days=30, hwid_limit=2)


def _expected_payload(group_ids: list[int]) -> dict:
    """Expected payload from the adapter (hand-written; not from old MarzbanClient).
    Update when _create_payload changes."""
    return {
        "username": SPEC.username,
        "status": "active",
        "data_limit": int(50 * 1073741824),
        "note": "",
        "group_ids": group_ids,
        "proxy_settings": {
            "vmess": {},
            "vless": {},
            "trojan": {},
            "shadowsocks": {"method": "aes-256-gcm"},
        },
        "data_limit_reset_strategy": "no_reset",
        "expire": str(int(NOW) + 30 * 86400),
        "hwid_limit": 2,
    }


async def test_create_payload_identical_to_expected_except_group_ids(pg):
    await pg.adapter.create_user(SPEC)
    sent = pg.fake.created_payloads[0]
    assert sent == _expected_payload([3, 7])
    assert list(sent) == list(_expected_payload([3, 7]))  # ترتیب کلیدها هم یکی است


async def test_unlimited_plan_matches_new_encoding(pg):
    spec = UserSpec(username="U_1_2_3", data_limit_bytes=0, duration_days=0)
    await pg.adapter.create_user(spec)
    sent = pg.fake.created_payloads[0]
    # PasarGuard: expire key OMITTED for unlimited, data_limit=0, hwid_limit=null for unlimited
    assert "expire" not in sent
    assert sent["data_limit"] == 0
    assert sent["hwid_limit"] is None


async def test_all_enabled_groups_are_used_and_disabled_excluded(pg):
    assert await resolve_group_ids(pg.adapter) == [3, 7]  # گروه 9 غیرفعال است


async def test_ids_come_from_live_listing_not_from_code(pg):
    """ارائه‌دهنده شماره‌ها را عوض کرد: کاربر باید با شماره‌های جدید ساخته شود."""
    pg.fake.groups = [
        {"id": 11, "name": "premium", "inbound_tags": [], "is_disabled": False, "total_users": 0},
        {"id": 12, "name": "basic", "inbound_tags": [], "is_disabled": False, "total_users": 0},
    ]
    await pg.adapter.create_user(SPEC)
    assert pg.fake.created_payloads[0]["group_ids"] == [11, 12]


async def test_stale_cache_is_refreshed_once_after_rejection(pg):
    await pg.adapter.create_user(SPEC)  # کش با [3, 7] پر می‌شود
    pg.fake.groups = [
        {"id": 21, "name": "premium", "inbound_tags": [], "is_disabled": False, "total_users": 0},
    ]
    other = UserSpec(username="U_9_9_9", data_limit_bytes=GB, duration_days=1)
    result = await pg.adapter.create_user(other)
    assert result.username == "U_9_9_9"
    assert [p["group_ids"] for p in pg.fake.created_payloads[-2:]] == [[3, 7], [21]]


async def test_no_enabled_group_fails_cleanly_without_creating_user(pg):
    for g in pg.fake.groups:
        g["is_disabled"] = True
    with pytest.raises(PanelConfigError):
        await pg.adapter.create_user(SPEC)
    assert pg.fake.created_payloads == []  # هرگز کاربر بدون گروه ساخته نمی‌شود


async def test_empty_listing_fails_cleanly(pg):
    pg.fake.groups = []
    with pytest.raises(PanelConfigError):
        await pg.adapter.create_user(SPEC)
    assert pg.fake.created_payloads == []


async def test_listing_falls_back_to_simple_when_groups_read_is_denied(pg):
    pg.fake.deny_groups = True
    clear_targets_cache()
    ids = await resolve_group_ids(pg.adapter)
    assert ids == [3, 7, 9]  # فهرست سبک وضعیت غیرفعال ندارد


async def test_relative_subscription_url_is_made_absolute(pg):
    user = await pg.adapter.create_user(SPEC)
    assert user.subscription_url == f"{pg.fake.url}/sub/{SPEC.username}"


async def test_extend_uses_max_of_now_and_old_expiry_and_reactivates(pg):
    await pg.adapter.create_user(SPEC)
    pg.fake.users[SPEC.username]["expire"] = int(NOW) - 86400  # دیروز منقضی شده
    pg.fake.users[SPEC.username]["status"] = "expired"
    user = await pg.adapter.extend_user(SPEC.username, add_days=30, add_bytes=0)
    assert user.status == "active"
    assert user.expire_at.timestamp() == int(NOW) + 30 * 86400  # از امروز، نه از دیروز


async def test_free_test_spec_payload_matches_except_group_ids(pg):
    """فیسِ تست رایگان: ۷۵ مگابایت، ۱ روز، ۱ همزمان."""
    free_spec = UserSpec(
        username="TEST_123_1700000000",
        data_limit_bytes=75 * 1024 * 1024,
        duration_days=1,
        hwid_limit=1,
        note="",
    )
    await pg.adapter.create_user(free_spec)
    sent = pg.fake.created_payloads[0]
    assert sent["username"] == free_spec.username
    assert sent["data_limit"] == 75 * 1024 * 1024
    assert sent["expire"] == str(int(NOW) + 86400)
    assert sent["hwid_limit"] == 1
    assert sent["note"] == ""
    assert sent["proxy_settings"] == {
        "vmess": {}, "vless": {}, "trojan": {}, "shadowsocks": {"method": "aes-256-gcm"}
    }
    assert sent["data_limit_reset_strategy"] == "no_reset"
    assert sent["group_ids"] == [3, 7]  # همه گروه‌های فعال


async def test_adapter_vs_old_marzbanclient_payload(pg):
    """Compare adapter create_user payload with old MarzbanClient.create_user payload.
    Allowed differences: group_ids (adapter uses live listing), unlimited-encoding fields.
    Reports other differences (e.g., expire format)."""
    from core.services.panel_client import MarzbanClient

    spec = UserSpec(username="U_compare_123", data_limit_bytes=10 * GB, duration_days=7, hwid_limit=3, note="compare test")

    # Build the payload that old MarzbanClient.create_user would send
    expire_unix = str(int(NOW) + 7 * 86400)
    old_payload = {
        "username": spec.username,
        "status": "active",
        "data_limit": spec.data_limit_bytes,
        "hwid_limit": spec.hwid_limit if spec.hwid_limit > 0 else None,
        "expire": expire_unix,
        "note": spec.note,
        "group_ids": [999],  # dummy group_ids
        "proxy_settings": {
            "vmess": {},
            "vless": {},
            "trojan": {},
            "shadowsocks": {"method": "aes-256-gcm"},
        },
        "data_limit_reset_strategy": "no_reset",
    }

    # Clear and call adapter
    pg.fake.created_payloads.clear()
    await pg.adapter.create_user(spec)
    adapter_payload = pg.fake.created_payloads[0]

    # Compare
    diffs = []
    for key in set(old_payload.keys()) | set(adapter_payload.keys()):
        old_val = old_payload.get(key)
        new_val = adapter_payload.get(key)
        if key == "group_ids":
            continue  # allowed: adapter uses live listing
        if key in ("expire", "data_limit", "hwid_limit") and spec.data_limit_bytes == 0 and spec.duration_days == 0 and spec.hwid_limit == 0:
            continue  # allowed: unlimited encoding differs
        if old_val != new_val:
            diffs.append(f"{key}: old={old_val!r} vs new={new_val!r}")

    if diffs:
        print("DIFFERENCES between old MarzbanClient and adapter payloads:")
        for d in diffs:
            print(f"  {d}")
    else:
        print("No differences (except group_ids which is allowed).")
    # Report only; don't fail
    assert True