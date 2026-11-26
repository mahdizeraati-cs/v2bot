"""Username utilities for panel username generation and validation.

This module contains pure functions for:
- Validating user-chosen names
- Normalizing names for panel usernames
- Building panel usernames (new format: U_<name>_<tx_id>)
- Legacy panel username generation (backward compatibility)
"""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

# Marzban validator limit (verified from official source)
PANEL_USERNAME_MAX = 32

# Maximum tx_id digits reserved in new format (8 digits = 99,999,999 transactions)
TX_ID_MAX_DIGITS = 8

# Reserved words that cannot be used as names
RESERVED_WORDS = {"admin", "owner", "support", "test", "root"}

# Prefix for test users
ZZ_SMOKE_PREFIX = "zz_smoke"


def validate_name(name: str) -> tuple[bool, str]:
    """Validate a user-chosen name.

    Rules:
    - Latin letters, digits, underscore only
    - Must start with a letter
    - Min 3 characters, max 21 characters (derived from PANEL_USERNAME_MAX - prefix - separator - TX_ID_MAX_DIGITS)
    - No consecutive underscores (__)
    - No leading or trailing underscore
    - Cannot be all digits
    - Cannot be reserved words (admin, owner, support, test, root)
    - Cannot start with "zz_smoke"

    Returns:
        tuple[bool, str]: (is_valid, error_message_in_persian)
    """
    if not name:
        return False, "نام نمی‌تواند خالی باشد."

    # Check length
    if len(name) < 3:
        return False, "نام باید حداقل ۳ کاراکتر باشد."

    # Reserved words (case-insensitive) - check early
    name_lower = name.lower()
    if name_lower in RESERVED_WORDS:
        return False, f"نام «{name}» محفوظ است و قابل استفاده نیست."

    # zz_smoke prefix reserved for test users - check early
    if name_lower.startswith(ZZ_SMOKE_PREFIX):
        return False, "این نام برای تست‌های سیستمی محفوظ است."

    # Max name length: PANEL_USERNAME_MAX - len("U_") - 1 separator - TX_ID_MAX_DIGITS
    max_name_len = PANEL_USERNAME_MAX - len("U_") - 1 - TX_ID_MAX_DIGITS  # = 21
    if len(name) > max_name_len:
        return False, f"نام نمی‌تواند بیش از {max_name_len} کاراکتر باشد."

    # Check charset: only Latin letters, digits, underscore
    if not re.match(r"^[a-zA-Z0-9_]+$", name):
        return False, "نام فقط می‌تواند شامل حروف لاتین، اعداد و زیرخط (_) باشد."

    # Cannot be all digits
    if name.isdigit():
        return False, "نام نمی‌تواند فقط از اعداد تشکیل شود."

    # Must start with a letter
    if not name[0].isalpha():
        return False, "نام باید با حرف شروع شود."

    # No leading underscore
    if name.startswith("_"):
        return False, "نام نمی‌تواند با زیرخط (_) شروع شود."

    # No trailing underscore
    if name.endswith("_"):
        return False, "نام نمی‌تواند با زیرخط (_) تمام شود."

    # No consecutive underscores
    if "__" in name:
        return False, "نام نمی‌تواند شامل دو زیرخط (__) پشت سر هم باشد."

    return True, ""


def normalize_name(name: str) -> str:
    """Normalize name for panel username (lowercase)."""
    return name.lower()


def build_panel_username(name: str, tx_id: int) -> str:
    """Build panel username using new format: U_<normalized_name>_<tx_id>

    The name is normalized to lowercase for the panel username.
    If tx_id exceeds the reserved 8 digits, return empty string to signal overflow.
    The caller (build_panel_username_with_fallback) will then use legacy format.

    Overflow strategy:
    - Normal case (tx_id <= 8 digits): U_<name>_<tx_id>
    - Overflow case (tx_id > 8 digits): Return empty string, caller uses legacy format
      This is logged explicitly as an overflow event, not a silent fallback.

    Args:
        name: User-chosen name (already validated, max 21 chars)
        tx_id: Transaction ID

    Returns:
        Panel username string, or empty string if overflow
    """
    normalized = normalize_name(name)
    tx_id_str = str(tx_id)

    # Check for overflow: tx_id exceeds reserved 8 digits
    if len(tx_id_str) > TX_ID_MAX_DIGITS:
        # Explicit overflow strategy: tx_id exceeds reserved 8 digits
        # We cannot truncate the name (requirement), so we must use legacy format
        # This is logged explicitly as an overflow event, not a silent fallback
        logger.warning(
            "Panel username overflow: tx_id=%d digits exceeds reserved %d digits, "
            "using legacy format with telegram_id and timestamp",
            len(tx_id_str),
            TX_ID_MAX_DIGITS,
        )
        # Return empty to signal overflow; caller must use legacy function
        return ""

    # New format: U_<name>_<tx_id>
    username = f"U_{normalized}_{tx_id_str}"

    # Sanity check: should never exceed PANEL_USERNAME_MAX with validated inputs
    if len(username) > PANEL_USERNAME_MAX:
        logger.error(
            "Panel username unexpectedly exceeds max: %s (len=%d)",
            username, len(username)
        )
        return ""

    return username


def build_panel_username_with_fallback(
    name: str, tx_id: int, telegram_id: int, timestamp: int
) -> str:
    """Build panel username with explicit overflow handling.

    This is the main entry point for new purchases. It tries the new format first,
    and if tx_id exceeds the reserved digits, explicitly falls back to legacy format.

    Args:
        name: User-chosen name (already validated)
        tx_id: Transaction ID
        telegram_id: User's Telegram ID (for legacy fallback)
        timestamp: Unix timestamp (for legacy fallback)

    Returns:
        Panel username string (new format or legacy format on overflow)
    """
    username = build_panel_username(name, tx_id)
    if username:
        return username

    # Overflow: explicitly use legacy format with timestamp
    # This is the documented overflow strategy, not a silent fallback
    return legacy_panel_username_from_timestamp(telegram_id, tx_id, timestamp)


def legacy_panel_username(telegram_id: int, tx_id: int, created_at: datetime) -> str:
    """Reproduce EXACTLY the current formula: U_{telegram_id}_{tx.id}_{int(tx.created_at.timestamp())}

    This must be byte-identical to the current implementation for backward compatibility.

    Args:
        telegram_id: User's Telegram ID
        tx_id: Transaction ID
        created_at: Transaction creation datetime (timezone-aware)

    Returns:
        Legacy panel username string
    """
    timestamp = int(created_at.timestamp())
    return f"U_{telegram_id}_{tx_id}_{timestamp}"


def legacy_panel_username_from_timestamp(telegram_id: int, tx_id: int, timestamp: int) -> str:
    """Legacy panel username from explicit timestamp (for fallback).

    Args:
        telegram_id: User's Telegram ID
        tx_id: Transaction ID
        timestamp: Unix timestamp (already int)

    Returns:
        Legacy panel username string
    """
    return f"U_{telegram_id}_{tx_id}_{timestamp}"