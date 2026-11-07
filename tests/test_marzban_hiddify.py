from __future__ import annotations

from datetime import date

import pytest

from core.panels import PanelConfigError, PanelType, UserSpec, adapter_from_fields, get_adapter
from core.panels.common import GB
from core.panels.hiddify import UNLIMITED_DAYS, UNLIMITED_GB, HiddifyAdapter
from tests.conftest import TODAY

SPEC = UserSpec(username="U_123_45_1700000000", data_limit_bytes=5 * GB, duration_days=30)


# ---------------------------------------------------------------- Marzban
async def test_marzban_sends_explicit_proxies_and_all_inbounds(marzban):
    await marzban.adapter.create_user(SPEC)
    sent = marzban.fake.created_payloads[0]
    assert sent["proxies"] == {"vless": {}, "vmess": {}}
    assert sent["inbounds"] == {"vless": ["VLESS TCP"], "vmess": ["VMess WS"]}
    assert "group_ids" not in sent


async def test_marzban_rejects_invalid_username_before_calling_panel(marzban):
    bad = UserSpec(username="U_" + "1" * 40, data_limit_bytes=GB, duration_days=1)
    with pytest.raises(PanelConfigError):
        await marzban.adapter.create_user(bad)
    assert marzban.fake.created_payloads == []


async def test_marzban_without_inbounds_fails_cleanly(marzban):
    marzban.fake.INBOUNDS = {}
    with pytest.raises(PanelConfigError):
        await marzban.adapter.create_user(SPEC)
    assert marzban.fake.created_payloads == []


# ---------------------------------------------------------------- Hiddify
async def test_hiddify_converts_units_in_one_place(hiddify):
    await hiddify.adapter.create_user(SPEC)
    sent = hiddify.fake.created_payloads[0]
    assert sent["usage_limit_GB"] == 5.0
    assert sent["package_days"] == 30
    assert sent["start_date"] == TODAY.isoformat()
    assert sent["uuid"] == hiddify.adapter.remote_id_for(SPEC.username)


async def test_hiddify_unlimited_uses_documented_sentinels(hiddify):
    unlimited = UserSpec(username="U_1_2_3", data_limit_bytes=0, duration_days=0)
    user = await hiddify.adapter.create_user(unlimited)
    sent = hiddify.fake.created_payloads[0]
    assert sent["usage_limit_GB"] == UNLIMITED_GB and sent["package_days"] == UNLIMITED_DAYS
    assert user.data_limit_bytes == 0 and user.expire_at is None  # برای بقیه‌ی کد «نامحدود» دیده می‌شود


async def test_hiddify_subscription_url_uses_client_path(hiddify):
    user = await hiddify.adapter.create_user(SPEC)
    host = hiddify.fake.url.removeprefix("http://")
    assert user.subscription_url == f"https://{host}/clientpath/{user.remote_id}/"


async def test_hiddify_remote_id_is_deterministic_per_server_seed(hiddify):
    a = hiddify.adapter
    assert a.remote_id_for("x") == a.remote_id_for("x") != a.remote_id_for("y")
    other = HiddifyAdapter(
        base_url=hiddify.fake.url, api_key="KEY", config={"admin_proxy_path": "adminpath"}, seed="srv-2"
    )
    assert other.remote_id_for("x") != a.remote_id_for("x")
    await other.aclose()


async def test_hiddify_expired_user_restarts_from_today_and_resets_usage(hiddify):
    await hiddify.adapter.create_user(SPEC)
    rid = hiddify.adapter.remote_id_for(SPEC.username)
    raw = hiddify.fake.users[rid]
    raw["start_date"] = date(2023, 1, 1).isoformat()  # ۳۰ روزه، مدت‌هاست تمام شده
    raw["current_usage_GB"] = 4.9
    assert (await hiddify.adapter.get_user(rid)).status == "expired"
    user = await hiddify.adapter.extend_user(rid, add_days=30, add_bytes=0)
    assert raw["start_date"] == TODAY.isoformat() and raw["package_days"] == 30
    assert raw["current_usage_GB"] == 0
    assert user.status == "active"


async def test_hiddify_active_user_adds_days_to_remaining_time(hiddify):
    await hiddify.adapter.create_user(SPEC)
    rid = hiddify.adapter.remote_id_for(SPEC.username)
    await hiddify.adapter.extend_user(rid, add_days=10, add_bytes=0)
    assert hiddify.fake.users[rid]["package_days"] == 40


async def test_hiddify_ping_falls_back_to_info(hiddify):
    hiddify.fake.has_ping = False
    await hiddify.adapter.ping()


async def test_hiddify_requires_admin_proxy_path():
    with pytest.raises(PanelConfigError):
        HiddifyAdapter(base_url="https://h.example.com", api_key="k", config={})


async def test_hiddify_has_no_targets(hiddify):
    assert hiddify.adapter.supports_targets is False
    assert await hiddify.adapter.list_targets() == []


# ---------------------------------------------------------------- factory
def test_factory_defaults_legacy_rows_to_pasarguard():
    from types import SimpleNamespace

    legacy = SimpleNamespace(id=1, panel_url="https://p.example.com", username="u", password="p")
    assert get_adapter(legacy).panel_type is PanelType.PASARGUARD


def test_factory_builds_each_type_from_form_fields():
    hiddify = adapter_from_fields(
        PanelType.HIDDIFY,
        {
            "base_url": "https://h.example.com/",
            "admin_proxy_path": "/adm/",
            "api_key": "k",
            "client_proxy_path": "c",
        },
    )
    assert hiddify.panel_type is PanelType.HIDDIFY
    marz = adapter_from_fields(
        PanelType.MARZBAN, {"base_url": "https://m.example.com", "username": "u", "password": "p"}
    )
    assert marz.panel_type is PanelType.MARZBAN
    pg = adapter_from_fields(
        PanelType.PASARGUARD, {"base_url": "https://p.example.com", "username": "u", "password": "p"}
    )
    assert pg.panel_type is PanelType.PASARGUARD


def test_factory_honours_verify_ssl_flag_per_server():
    from types import SimpleNamespace

    srv = SimpleNamespace(
        id=2,
        panel_type="pasarguard",
        panel_url="https://p",
        username="u",
        password="p",
        panel_config={"verify_ssl": False},
    )
    assert get_adapter(srv).http.verify_ssl is False
    srv.panel_config = {}
    assert get_adapter(srv).http.verify_ssl is True
