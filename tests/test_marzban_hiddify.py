from __future__ import annotations

from datetime import date
from aiohttp import web

import pytest

from core.panels import PanelConfigError, PanelType, UserSpec, adapter_from_fields, get_adapter
from core.panels.common import GB
from core.panels.hiddify import UNLIMITED_DAYS, UNLIMITED_GB, HiddifyAdapter
from core.panels.base import PanelAuthError, PanelRejected, PanelUnreachable
from tests.conftest import TODAY
from tests.fake_panels import FakeHiddify, _json

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


# ---------------------------------------------------------------- _parse_hiddify_admin_link tests

def test_parse_hiddify_admin_link_with_admin_segment():
    """Test parsing admin link with /admin/ segment."""
    from bot.handlers.admin_handlers import _parse_hiddify_admin_link
    
    link = "https://panel-03.example-admin.de/sXDm8ZxnkWl5kI4RppukoBGLx8E/6e99c40f-0419-417f-8d6f-08af3bc74801/admin/#REZZ"
    result = _parse_hiddify_admin_link(link)
    
    assert result is not None
    assert result["base_url"] == "https://panel-03.example-admin.de"
    assert result["admin_proxy_path"] == "sXDm8ZxnkWl5kI4RppukoBGLx8E"
    assert result["api_key"] == "6e99c40f-0419-417f-8d6f-08af3bc74801"


def test_parse_hiddify_admin_link_without_admin_segment():
    """Test parsing admin link without /admin/ segment (real production format)."""
    from bot.handlers.admin_handlers import _parse_hiddify_admin_link
    
    link = "https://panel-03.example-admin.de/sXDm8ZxnkWl5kI4RppukoBGLx8E/6e99c40f-0419-417f-8d6f-08af3bc74801/#REZZ"
    result = _parse_hiddify_admin_link(link)
    
    assert result is not None
    assert result["base_url"] == "https://panel-03.example-admin.de"
    assert result["admin_proxy_path"] == "sXDm8ZxnkWl5kI4RppukoBGLx8E"
    assert result["api_key"] == "6e99c40f-0419-417f-8d6f-08af3bc74801"


def test_parse_hiddify_admin_link_without_fragment():
    """Test parsing admin link without fragment."""
    from bot.handlers.admin_handlers import _parse_hiddify_admin_link
    
    link = "https://panel-03.example-admin.de/sXDm8ZxnkWl5kI4RppukoBGLx8E/6e99c40f-0419-417f-8d6f-08af3bc74801/admin/"
    result = _parse_hiddify_admin_link(link)
    
    assert result is not None
    assert result["base_url"] == "https://panel-03.example-admin.de"
    assert result["admin_proxy_path"] == "sXDm8ZxnkWl5kI4RppukoBGLx8E"
    assert result["api_key"] == "6e99c40f-0419-417f-8d6f-08af3bc74801"


def test_parse_hiddify_admin_link_invalid_uuid():
    """Test parsing admin link with invalid UUID returns None."""
    from bot.handlers.admin_handlers import _parse_hiddify_admin_link
    
    link = "https://panel.example.com/adminpath/invalid-uuid/admin/"
    result = _parse_hiddify_admin_link(link)
    
    assert result is None


def test_parse_hiddify_admin_link_missing_components():
    """Test parsing admin link with missing components returns None."""
    from bot.handlers.admin_handlers import _parse_hiddify_admin_link
    
    # Missing UUID
    result = _parse_hiddify_admin_link("https://panel.example.com/adminpath/")
    assert result is None
    
    # Missing admin path
    result = _parse_hiddify_admin_link("https://panel.example.com/6e99c40f-0419-417f-8d6f-08af3bc74801/admin/")
    assert result is None


def test_parse_hiddify_admin_link_invalid_url():
    """Test parsing invalid URL returns None."""
    from bot.handlers.admin_handlers import _parse_hiddify_admin_link

    result = _parse_hiddify_admin_link("not-a-url")
    assert result is None

    result = _parse_hiddify_admin_link("")
    assert result is None


# ---------------------------------------------------------------- _subscription_url tests

async def test_hiddify_subscription_url_uses_full_url_template(hiddify):
    """Test _subscription_url uses full URL template as-is when configured."""
    # Set a full URL template with different domain
    hiddify.adapter.config["sub_url_template"] = "https://sub.example.com/clientpath/{uuid}/sub64/"
    
    user = await hiddify.adapter.create_user(SPEC)
    
    # Should use the template's domain, not the panel's domain
    assert user.subscription_url == f"https://sub.example.com/clientpath/{user.remote_id}/sub64/"


async def test_hiddify_subscription_url_legacy_template(hiddify):
    """Test _subscription_url works with legacy template format."""
    from core.panels.hiddify import DEFAULT_SUB_TEMPLATE
    # Use default template (legacy format with {domain} placeholder)
    hiddify.adapter.config["sub_url_template"] = DEFAULT_SUB_TEMPLATE
    
    user = await hiddify.adapter.create_user(SPEC)
    
    # Should use panel's domain
    host = hiddify.fake.url.removeprefix("http://")
    expected = f"https://{host}/clientpath/{user.remote_id}/"
    assert user.subscription_url == expected


async def test_hiddify_subscription_url_no_client_path_returns_empty(hiddify):
    """Test _subscription_url returns empty string when client_path missing in legacy template."""
    from core.panels.hiddify import DEFAULT_SUB_TEMPLATE
    hiddify.adapter.config["sub_url_template"] = DEFAULT_SUB_TEMPLATE
    hiddify.adapter.config["client_proxy_path"] = ""
    
    user = await hiddify.adapter.create_user(SPEC)
    
    assert user.subscription_url == ""


# ---------------------------------------------------------------- H5 fallback tests

async def test_hiddify_get_user_fallback_to_list(hiddify):
    """Test _get_raw falls back to list+filter when direct GET returns 404 (H5)."""
    from core.panels.base import PanelRejected
    
    # Create a user first
    await hiddify.adapter.create_user(SPEC)
    rid = hiddify.adapter.remote_id_for(SPEC.username)
    
    # Mock _api to raise 404 on direct GET, then return list on fallback
    original_api = hiddify.adapter._api
    
    call_count = {"count": 0}
    
    async def mock_api(method, path, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1 and path == f"/admin/user/{rid}/":
            # First call (direct GET) returns 404
            raise PanelRejected("User not found", status=404)
        elif call_count["count"] == 2 and path == "/admin/user/":
            # Second call (list) returns user list
            return [{"uuid": rid, "name": SPEC.username, "enable": True, "usage_limit_GB": 5.0, "package_days": 30, "start_date": "2024-01-01", "current_usage_GB": 0.0, "mode": "no_reset"}]
        return await original_api(method, path, **kwargs)
    
    hiddify.adapter._api = mock_api
    
    # Should succeed via fallback
    user = await hiddify.adapter.get_user(rid)
    
    assert user is not None
    assert user.remote_id == rid
    assert call_count["count"] == 2


async def test_hiddify_get_user_fallback_not_found(hiddify):
    """Test _get_raw returns None when user not found in list either."""
    from core.panels.base import PanelRejected
    
    rid = "00000000-0000-0000-0000-000000000000"
    
    # Mock _api to raise 404 on direct GET, then return empty list on fallback
    original_api = hiddify.adapter._api
    
    call_count = {"count": 0}
    
    async def mock_api(method, path, **kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1 and path == f"/admin/user/{rid}/":
            raise PanelRejected("User not found", status=404)


# ---------------------------------------------------------------- ping error handling tests

class FakeHiddifyAuthError(FakeHiddify):
    """Fake panel that returns 401 on /admin/me/."""
    async def me(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        return _json({"detail": "Unauthorized"}, 401)


class FakeHiddify404(FakeHiddify):
    """Fake panel that returns 404 on /panel/info/."""
    async def info(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        return _json({"detail": "Not found"}, 404)


class FakeHiddify500(FakeHiddify):
    """Fake panel that returns 500 on /panel/info/."""
    async def info(self, request: web.Request) -> web.Response:
        if not self._auth(request):
            return self._denied()
        return _json({"detail": "Server error"}, 500)


async def test_hiddify_ping_401_raises_autherror():
    """Test ping() raises PanelAuthError on 401/403."""
    fake = FakeHiddifyAuthError(api_key="VALID_KEY")
    await fake.start(fake.app())
    try:
        adapter = HiddifyAdapter(
            base_url=fake.url,
            api_key="WRONG_KEY",
            config={"admin_proxy_path": "adminpath"},
        )
        with pytest.raises(PanelAuthError):
            await adapter.ping()
    finally:
        await adapter.aclose()
        await fake.stop()


async def test_hiddify_ping_404_raises_rejected():
    """Test ping() raises PanelRejected on 404."""
    fake = FakeHiddify404(api_key="VALID_KEY")
    await fake.start(fake.app())
    try:
        adapter = HiddifyAdapter(
            base_url=fake.url,
            api_key="VALID_KEY",
            config={"admin_proxy_path": "adminpath"},
        )
        with pytest.raises(PanelRejected) as exc_info:
            await adapter.ping()
        assert exc_info.value.status == 404
    finally:
        await adapter.aclose()
        await fake.stop()


async def test_hiddify_ping_500_raises_unreachable():
    """Test ping() raises PanelUnreachable on 5xx."""
    fake = FakeHiddify500(api_key="VALID_KEY")
    await fake.start(fake.app())
    try:
        adapter = HiddifyAdapter(
            base_url=fake.url,
            api_key="VALID_KEY",
            config={"admin_proxy_path": "adminpath"},
        )
        with pytest.raises(PanelUnreachable):
            await adapter.ping()
    finally:
        await adapter.aclose()
        await fake.stop()
