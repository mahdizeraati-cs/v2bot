"""ساخت آداپتور از روی ردیف Server (یا هر آبجکتی با همان فیلدها)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from core.panels.base import PanelAdapter, PanelConfigError, PanelType
from core.panels.hiddify import HiddifyAdapter
from core.panels.marzban import MarzbanAdapter
from core.panels.pasarguard import PasarGuardAdapter


def get_adapter(server: Any) -> PanelAdapter:
    """ردیف‌های قدیمی بدون panel_type به‌عنوان PasarGuard شناخته می‌شوند."""
    try:
        ptype = PanelType(getattr(server, "panel_type", None) or PanelType.PASARGUARD.value)
    except ValueError as exc:
        raise PanelConfigError("نوع پنل ناشناخته است.") from exc
    config = dict(getattr(server, "panel_config", None) or {})
    verify_ssl = config.get("verify_ssl", True) is not False
    server_id = getattr(server, "id", None)
    cache_key = f"srv:{server_id}" if server_id else f"tmp:{server.panel_url}|{server.username}"

    if ptype is PanelType.HIDDIFY:
        return HiddifyAdapter(
            base_url=server.panel_url,
            api_key=server.password,
            config=config,
            verify_ssl=verify_ssl,
            cache_key=cache_key,
            seed=str(server_id) if server_id else None,
        )
    cls = MarzbanAdapter if ptype is PanelType.MARZBAN else PasarGuardAdapter
    return cls(
        base_url=server.panel_url,
        username=server.username,
        password=server.password,
        verify_ssl=verify_ssl,
        cache_key=cache_key,
        config=config,
    )


def server_kwargs_from_fields(panel_type: PanelType, values: dict[str, str]) -> dict[str, Any]:
    """مقادیر فرم ثبت‌سرور -> ستون‌های Server (panel_url/username/password/panel_config)."""
    config: dict[str, Any] = {}
    if panel_type is PanelType.HIDDIFY:
        config["admin_proxy_path"] = values["admin_proxy_path"].strip().strip("/")
        config["client_proxy_path"] = values["client_proxy_path"].strip().strip("/")
        return {
            "panel_type": panel_type.value,
            "panel_url": values["base_url"].strip().rstrip("/"),
            "username": "hiddify",  # ستون NOT NULL است؛ Hiddify نام کاربری ندارد
            "password": values["api_key"].strip(),
            "panel_config": config,
        }
    return {
        "panel_type": panel_type.value,
        "panel_url": values["base_url"].strip().rstrip("/"),
        "username": values["username"].strip(),
        "password": values["password"].strip(),
        "panel_config": config,
    }


def adapter_from_fields(panel_type: PanelType, values: dict[str, str]) -> PanelAdapter:
    """آداپتور موقت برای تست اتصال قبل از ذخیره‌ی سرور."""
    return get_adapter(SimpleNamespace(id=None, **server_kwargs_from_fields(panel_type, values)))
