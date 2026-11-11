"""قرارداد مشترک آداپتورهای پنل (PasarGuard / Marzban / Hiddify)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class PanelType(StrEnum):
    PASARGUARD = "pasarguard"
    MARZBAN = "marzban"
    HIDDIFY = "hiddify"


PANEL_TYPE_LABELS_FA = {
    PanelType.PASARGUARD: "پاسارگارد",
    PanelType.MARZBAN: "مرزبان",
    PanelType.HIDDIFY: "هیدیفای",
}


# ---------------------------------------------------------------- errors
class PanelError(Exception):
    """پایه‌ی همه‌ی خطاهای لایه‌ی پنل. هیچ‌وقت شامل راز/توکن/لینک اشتراک نیست."""

    def __init__(self, message: str = "", *, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


class PanelAuthError(PanelError):
    """نام کاربری/رمز/کلید API اشتباه است (یا نشست منقضی شده)."""


class PanelUnreachable(PanelError):
    """timeout، قطع شبکه یا خطای 5xx؛ قابل تلاش مجدد."""


class PanelRejected(PanelError):
    """پنل درخواست را با 4xx رد کرد؛ قابل تلاش مجدد نیست."""


class PanelConfigError(PanelError):
    """پیکربندی ناقص (مثلاً هیچ گروه/اینباند قابل تخصیص نیست)."""


class PanelCapabilityError(PanelError):
    """این پنل قابلیت درخواستی را ندارد."""


def error_message_fa(err: PanelError) -> str:
    """پیام فارسی امن برای نمایش به ادمین/مشتری."""
    if isinstance(err, PanelAuthError):
        return "نام کاربری، رمز عبور یا کلید API پنل اشتباه است."
    if isinstance(err, PanelUnreachable):
        return "اتصال به پنل برقرار نشد (آدرس، پورت یا شبکه را بررسی کنید)."
    if isinstance(err, PanelConfigError):
        return f"پیکربندی پنل ناقص است: {err.message}" if err.message else "پیکربندی پنل ناقص است."
    if isinstance(err, PanelCapabilityError):
        return "این نوع پنل از عملیات درخواستی پشتیبانی نمی‌کند."
    if isinstance(err, PanelRejected):
        return f"پنل درخواست را رد کرد: {err.message}" if err.message else "پنل درخواست را رد کرد."
    return "خطای نامشخص در ارتباط با پنل."


# ---------------------------------------------------------------- data
@dataclass(frozen=True)
class CredentialField:
    key: str  # base_url, username, password, admin_proxy_path, ...
    prompt_fa: str
    secret: bool = False  # پیام ادمین بعد از خواندن پاک می‌شود
    validator: str | None = None  # url | path | nonempty
    required: bool = True  # whether this field is required


@dataclass(frozen=True)
class Target:
    """گروه (PasarGuard) یا اینباند (Marzban)."""

    remote_id: str
    name: str
    enabled: bool = True
    protocol: str | None = None


@dataclass(frozen=True)
class UserSpec:
    username: str
    data_limit_bytes: int  # 0 = نامحدود
    duration_days: int  # 0 = نامحدود
    note: str = ""
    hwid_limit: int = 0  # 0 = نامحدود/بدون محدودیت (فقط PasarGuard)


@dataclass(frozen=True)
class RemoteUser:
    remote_id: str
    username: str
    subscription_url: str  # همیشه absolute (هرگز لاگ نشود)
    status: str  # active|disabled|limited|expired|on_hold
    used_bytes: int
    data_limit_bytes: int  # 0 = نامحدود
    expire_at: datetime | None  # None = نامحدود
    hwid_limit: int = 0  # 0 = نامحدود/بدون محدودیت


class PanelAdapter(Protocol):
    panel_type: PanelType
    supports_targets: bool

    def credential_schema(self) -> list[CredentialField]: ...
    def remote_id_for(self, username: str) -> str: ...
    async def ping(self) -> None: ...
    async def list_targets(self) -> list[Target]: ...
    async def create_user(self, spec: UserSpec) -> RemoteUser: ...
    async def get_user(self, remote_id: str) -> RemoteUser | None: ...
    async def extend_user(self, remote_id: str, add_days: int, add_bytes: int) -> RemoteUser: ...
    async def set_enabled(self, remote_id: str, enabled: bool) -> RemoteUser: ...
    async def delete_user(self, remote_id: str) -> None: ...
    async def aclose(self) -> None: ...
