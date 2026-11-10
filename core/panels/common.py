"""توابع کمکی مشترک آداپتورها."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

GB = 1024**3


def parse_expire(value: Any) -> datetime | None:
    """None/0/"0" -> نامحدود (None)؛ عدد یا رشته‌ی عددی -> unix؛ رشته‌ی ISO -> datetime (UTC)."""
    if value in (None, "", 0, "0"):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value), tz=UTC)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return None


def origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def absolute_url(url: str, base_url: str) -> str:
    """لینک اشتراکِ نسبی (/sub/...) را با origin پنل absolute می‌کند."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return origin_of(base_url) + (url if url.startswith("/") else "/" + url)


_URL_RE = re.compile(r"^https?://[^\s/]+(:\d+)?(/\S*)?$")
_PATH_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


def validate_field(kind: str | None, value: str) -> str | None:
    """None اگر معتبر باشد؛ وگرنه پیام خطای فارسی."""
    value = value.strip()
    if not value:
        return "مقدار نمی‌تواند خالی باشد."
    if kind == "url" and not _URL_RE.match(value):
        return "آدرس باید با http:// یا https:// شروع شود (مثال: https://panel.example.com:8000)."
    if kind == "path" and not _PATH_RE.match(value.strip("/")):
        return "مسیر فقط می‌تواند شامل حروف انگلیسی، عدد، - و _ باشد (بدون اسلش داخلی)."
    return None


# --- Unlimited encoding (U1a-U1d) ----------------------------------------
#.panel_type values: "pasarguard" | "marzban" | "hiddify"
# Returns value to PUT IN REQUEST BODY (not for storage).
# For unlimited: PasarGuard -> omit key (return special sentinel), Marzban -> 0, Hiddify -> sentinel.

def encode_expire(panel_type: str, duration_days: int, now: float) -> int | str | None:
    """Encode duration_days for create/extend request.
    0 (unlimited) -> PasarGuard: None (omit key), Marzban: 0, Hiddify: UNLIMITED_DAYS.
    >0 -> unix timestamp (int) for PasarGuard/Marzban, days (int) for Hiddify.
    Raises ValueError if duration_days < 0."""
    if duration_days < 0:
        raise ValueError("duration_days cannot be negative")
    if duration_days == 0:
        if panel_type == "pasarguard":
            return None  # sentinel: omit key
        if panel_type == "marzban":
            return 0
        # hiddify
        from core.panels.hiddify import UNLIMITED_DAYS
        return UNLIMITED_DAYS
    # positive days
    if panel_type == "hiddify":
        return duration_days
    return int(now) + duration_days * 86400


def encode_data_limit(panel_type: str, data_limit_bytes: int) -> int | float | None:
    """Encode data_limit_bytes for create/extend request.
    0 (unlimited) -> PasarGuard: 0, Marzban: 0, Hiddify: UNLIMITED_GB.
    >0 -> bytes (int) for PasarGuard/Marzban, GB (float) for Hiddify.
    Raises ValueError if data_limit_bytes < 0."""
    if data_limit_bytes < 0:
        raise ValueError("data_limit_bytes cannot be negative")
    if data_limit_bytes == 0:
        if panel_type == "hiddify":
            from core.panels.hiddify import UNLIMITED_GB
            return UNLIMITED_GB
        return 0
    if panel_type == "hiddify":
        return data_limit_bytes / (1024**3)
    return data_limit_bytes


def encode_user_limit(panel_type: str, hwid_limit: int) -> int | None:
    """Encode hwid_limit for create/extend request.
    0 (unlimited) -> PasarGuard: None (omit/null), Marzban: N/A (no such field), Hiddify: N/A.
    >0 -> int for PasarGuard.
    Raises ValueError if hwid_limit < 0."""
    if hwid_limit < 0:
        raise ValueError("hwid_limit cannot be negative")
    if hwid_limit == 0:
        if panel_type == "pasarguard":
            return None
        # Marzban/Hiddify don't have this field
        return None
    if panel_type == "pasarguard":
        return hwid_limit
    return None
