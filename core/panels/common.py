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
