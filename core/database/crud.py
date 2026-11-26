import os
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, update, func
from sqlalchemy.exc import IntegrityError
from core.database.models import User, Vendor, Server, Partner, PartnerAudit


async def _get_next_vendor_round_robin(session: AsyncSession) -> int | None:
    """انتخاب نوبتی وندور (Round Robin) با استفاده از کوئریهای دیتابیس"""

    # ۱. پیدا کردن وندور آخرین کاربری که در سیستم ثبتنام کرده
    stmt_last_user = select(User.vendor_id).order_by(desc(User.id)).limit(1)
    last_vendor_id = (await session.execute(stmt_last_user)).scalar_one_or_none()

    if last_vendor_id is not None:
        # ۲. پیدا کردن وندور فعال بعدی (آیدی بزرگتر از آخرین وندور تخصیص یافته)
        stmt_next_vendor = select(Vendor.id).where(
            Vendor.is_active == True,
            Vendor.id > last_vendor_id
        ).order_by(Vendor.id.asc()).limit(1)
        next_vendor_id = (await session.execute(stmt_next_vendor)).scalar_one_or_none()

        if next_vendor_id is not None:
            return next_vendor_id

    # ۳. حلقه (Loop): اگر کاربری نبود، یا به انتهای لیست وندورها رسیدیم، برگرد به اولین وندور فعال
    stmt_first_vendor = select(Vendor.id).where(
        Vendor.is_active == True
    ).order_by(Vendor.id.asc()).limit(1)

    return (await session.execute(stmt_first_vendor)).scalar_one_or_none()


async def get_or_create_user(
    session: AsyncSession,
    telegram_id: int,
    deep_link_vendor_id: int | None = None,
) -> User | None:
    """گرفتن یا ساخت کاربر.

    قوانین پیوند فروشنده:
    - کاربر جدید: vendor_id از deep_link (اگر معتبر) وگرنه Round Robin.
    - کاربر موجود: هرگز vendor_id تغییر نمیکند (پیوند دائمی به اولین فروشنده).
    """
    owner_id_str = os.getenv("OWNER_ID")
    owner_id = int(owner_id_str) if owner_id_str else 0

    # ۱. احراز هویت مالک: اگر مالک ربات را استارت کرد، او را به عنوان وندور ثبت کن
    if telegram_id == owner_id:
        stmt_vendor = select(Vendor).where(Vendor.telegram_id == owner_id)
        vendor = (await session.execute(stmt_vendor)).scalar_one_or_none()
        if not vendor:
            new_vendor = Vendor(
                telegram_id=owner_id,
                name="Owner",
                is_active=True
            )
            session.add(new_vendor)
            # flush میکنیم تا وندور در همین سشن ثبت بشه و بتونیم به عنوان یوزر هم ثبتش کنیم
            await session.flush()

    # ۲. بررسی اینکه آیا کاربر از قبل وجود دارد؟
    stmt_user = select(User).where(User.telegram_id == telegram_id)
    user = (await session.execute(stmt_user)).scalar_one_or_none()

    # 🌟 [Bug 1 Fix] کاربر موجود: vendor_id هرگز تغییر نمیکند. پیوند دائمی است.
    if user is not None:
        return user

    # ۳. کاربر جدید است: تعیین vendor_id نهایی
    # اولویت اول: deep_link_vendor_id (اگر عدد مثبت معتبر باشد)
    assigned_vendor_id: int | None = None
    if deep_link_vendor_id is not None and deep_link_vendor_id > 0:
        # اعتبارسنجی وجود فروشنده هدف
        stmt_dl_vendor = select(Vendor.id).where(
            Vendor.id == deep_link_vendor_id,
            Vendor.is_active == True,
        )
        assigned_vendor_id = (await session.execute(stmt_dl_vendor)).scalar_one_or_none()

    # اولویت دوم: Round Robin اگر deep-link معتبر نبود
    if not assigned_vendor_id:
        assigned_vendor_id = await _get_next_vendor_round_robin(session)

    # گارد امنیتی: اگر هیچ وندوری (حتی مالک) هنوز در دیتابیس فعال نباشد
    if not assigned_vendor_id:
        return None

    # ۴. ساخت کاربر جدید و اتصال به وندورِ نهایی
    new_user = User(
        telegram_id=telegram_id,
        vendor_id=assigned_vendor_id,
        wallet_balance=0.0
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    return new_user


async def create_server(
    session: AsyncSession,
    name: str,
    panel_url: str,
    username: str,
    password: str,
    panel_type: str = "pasarguard",
    panel_config: dict[str, Any] | None = None,
    vendor_id: int | None = None,
    is_shared: bool = False,
) -> Server:
    """Create a new server with panel_type and panel_config."""
    server = Server(
        name=name,
        panel_url=panel_url,
        username=username,
        password=password,
        panel_type=panel_type,
        panel_config=panel_config,
        vendor_id=vendor_id,
        is_shared=is_shared,
    )
    session.add(server)
    await session.commit()
    await session.refresh(server)
    return server


class NameTaken(Exception):
    """Raised when the chosen name is already taken (case-insensitive)."""
    pass


async def set_name(
    session: AsyncSession,
    user_id: int,
    chosen_name: str,
    normalized_name: str,
) -> None:
    """Set the user's chosen name and normalized name (only if not already set).

    Args:
        session: Database session
        user_id: User's database ID
        chosen_name: Original spelling of the name (for display)
        normalized_name: Lowercase version (for uniqueness)

    Raises:
        NameTaken: If the normalized_name is already taken (IntegrityError on unique index)
                   or if the user already has a chosen_name (name is immutable)
    """
    # Precheck: see if normalized_name is already taken by another user
    # This improves UX by avoiding the IntegrityError round-trip in the common case.
    # The database unique index remains the final authority for concurrent requests.
    stmt_check = select(User.id).where(
        User.normalized_name == normalized_name,
        User.id != user_id
    )
    existing = await session.execute(stmt_check)
    if existing.scalar_one_or_none() is not None:
        raise NameTaken("این نام قبلاً توسط کاربر دیگری انتخاب شده است.")

    stmt = (
        update(User)
        .where(User.id == user_id, User.chosen_name.is_(None))
        .values(chosen_name=chosen_name, normalized_name=normalized_name)
    )
    try:
        result = await session.execute(stmt)
        if result.rowcount == 0:
            # No rows updated - either user doesn't exist or name already set
            # Check if user exists and has a name
            user = await session.get(User, user_id)
            if user and user.chosen_name:
                raise NameTaken("نام کاربری قبلاً ثبت شده و تغییر نام ممکن نیست.")
            # User doesn't exist - this shouldn't happen in normal flow
            raise NameTaken("کاربر یافت نشد.")
        await session.commit()
    except IntegrityError as e:
        await session.rollback()
        # Check if it's a unique violation on the normalized_name index
        # SQLSTATE 23505 = unique_violation
        if getattr(e, "code", None) == "23505" and "ix_users_normalized_name_unique" in str(e.orig):
            raise NameTaken("این نام قبلاً توسط کاربر دیگری انتخاب شده است.")
        # Re-raise unrelated integrity errors
        raise


async def get_name(session: AsyncSession, user_id: int) -> str | None:
    """Get the user's chosen name (original spelling).

    Args:
        session: Database session
        user_id: User's database ID

    Returns:
        The chosen_name if set, None otherwise
    """
    stmt = select(User.chosen_name).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ==================== Partner Repository Functions ====================

async def is_partner(session: AsyncSession, telegram_id: int) -> bool:
    """Check if a user is an active partner.

    Args:
        session: Database session
        telegram_id: User's Telegram ID

    Returns:
        True if user is an active partner, False otherwise
    """
    stmt = select(Partner).where(
        Partner.telegram_id == telegram_id,
        Partner.is_active == True
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def get_partner(session: AsyncSession, telegram_id: int) -> Partner | None:
    """Get partner record by Telegram ID.

    Args:
        session: Database session
        telegram_id: User's Telegram ID

    Returns:
        Partner object if found, None otherwise
    """
    stmt = select(Partner).where(Partner.telegram_id == telegram_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_partners(
    session: AsyncSession,
    vendor_id: int | None = None
) -> list[Partner]:
    """List all partners, optionally filtered by vendor.

    Args:
        session: Database session
        vendor_id: Optional vendor ID to filter by

    Returns:
        List of Partner objects
    """
    stmt = select(Partner)
    if vendor_id is not None:
        # Join with users to filter by vendor_id
        stmt = stmt.join(User, User.telegram_id == Partner.telegram_id).where(
            User.vendor_id == vendor_id
        )
    stmt = stmt.order_by(Partner.created_at.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def promote_partner(
    session: AsyncSession,
    customer_telegram_id: int,
    admin_telegram_id: int,
    min_topup_toman: int,
    discount_percent: int,
) -> Partner:
    """Promote an existing customer to wholesale partner.

    Args:
        session: Database session
        customer_telegram_id: Telegram ID of the customer to promote
        admin_telegram_id: Telegram ID of the admin/owner performing the promotion
        min_topup_toman: Minimum top-up amount in Toman (must be > 0)
        discount_percent: Discount percentage (1-90)

    Returns:
        The created/updated Partner object

    Raises:
        ValueError: If customer doesn't exist or invalid parameters
    """
    # Validate inputs
    if min_topup_toman <= 0:
        raise ValueError("min_topup_toman must be positive")
    if discount_percent < 1 or discount_percent > 90:
        raise ValueError("discount_percent must be between 1 and 90")

    # Check if customer exists
    stmt_user = select(User).where(User.telegram_id == customer_telegram_id)
    result = await session.execute(stmt_user)
    user = result.scalar_one_or_none()
    if user is None:
        raise ValueError(f"Customer with telegram_id {customer_telegram_id} not found")

    # Check if partner already exists
    existing_partner = await get_partner(session, customer_telegram_id)
    
    if existing_partner is not None:
        # Reactivation or terms update for existing partner
        old_values = {
            "is_active": existing_partner.is_active,
            "min_topup_toman": existing_partner.min_topup_toman,
            "discount_percent": existing_partner.discount_percent,
        }
        
        existing_partner.is_active = True
        existing_partner.added_by = admin_telegram_id
        existing_partner.min_topup_toman = min_topup_toman
        existing_partner.discount_percent = discount_percent
        existing_partner.updated_at = func.now()
        
        await session.flush()
        
        # Audit the promotion/reactivation
        audit = PartnerAudit(
            partner_telegram_id=customer_telegram_id,
            admin_telegram_id=admin_telegram_id,
            action_type="promote",
            old_values=old_values,
            new_values={
                "is_active": True,
                "min_topup_toman": min_topup_toman,
                "discount_percent": discount_percent,
            },
        )
        session.add(audit)
        
        await session.commit()
        await session.refresh(existing_partner)
        return existing_partner
    
    # Create new partner
    new_partner = Partner(
        telegram_id=customer_telegram_id,
        is_active=True,
        added_by=admin_telegram_id,
        min_topup_toman=min_topup_toman,
        discount_percent=discount_percent,
    )
    session.add(new_partner)
    await session.flush()
    
    # Audit the promotion
    audit = PartnerAudit(
        partner_telegram_id=customer_telegram_id,
        admin_telegram_id=admin_telegram_id,
        action_type="promote",
        old_values=None,
        new_values={
            "is_active": True,
            "min_topup_toman": min_topup_toman,
            "discount_percent": discount_percent,
        },
    )
    session.add(audit)
    
    await session.commit()
    await session.refresh(new_partner)
    return new_partner


async def update_partner_terms(
    session: AsyncSession,
    partner_telegram_id: int,
    admin_telegram_id: int,
    min_topup_toman: int | None = None,
    discount_percent: int | None = None,
) -> Partner:
    """Update partner terms (minimum top-up and/or discount percentage).

    Args:
        session: Database session
        partner_telegram_id: Telegram ID of the partner
        admin_telegram_id: Telegram ID of the admin/owner performing the update
        min_topup_toman: New minimum top-up amount (optional)
        discount_percent: New discount percentage (optional)

    Returns:
        The updated Partner object

    Raises:
        ValueError: If partner not found, not active, or invalid parameters
    """
    partner = await get_partner(session, partner_telegram_id)
    if partner is None:
        raise ValueError(f"Partner with telegram_id {partner_telegram_id} not found")
    
    if not partner.is_active:
        raise ValueError(f"Partner with telegram_id {partner_telegram_id} is not active")

    # Validate inputs
    if min_topup_toman is not None and min_topup_toman <= 0:
        raise ValueError("min_topup_toman must be positive")
    if discount_percent is not None and (discount_percent < 1 or discount_percent > 90):
        raise ValueError("discount_percent must be between 1 and 90")

    # Track old values for audit
    old_values = {
        "min_topup_toman": partner.min_topup_toman,
        "discount_percent": partner.discount_percent,
    }

    # Update fields if provided
    if min_topup_toman is not None:
        partner.min_topup_toman = min_topup_toman
    if discount_percent is not None:
        partner.discount_percent = discount_percent
    
    partner.updated_at = func.now()
    
    await session.flush()

    # Audit the terms change
    new_values = {
        "min_topup_toman": partner.min_topup_toman,
        "discount_percent": partner.discount_percent,
    }
    
    audit = PartnerAudit(
        partner_telegram_id=partner_telegram_id,
        admin_telegram_id=admin_telegram_id,
        action_type="update_terms",
        old_values=old_values,
        new_values=new_values,
    )
    session.add(audit)

    await session.commit()
    await session.refresh(partner)
    return partner


async def revoke_partner(
    session: AsyncSession,
    partner_telegram_id: int,
    admin_telegram_id: int,
) -> Partner:
    """Revoke partner status (deactivate).

    Args:
        session: Database session
        partner_telegram_id: Telegram ID of the partner
        admin_telegram_id: Telegram ID of the admin/owner performing the revocation

    Returns:
        The updated Partner object with is_active=False

    Raises:
        ValueError: If partner not found or already inactive
    """
    partner = await get_partner(session, partner_telegram_id)
    if partner is None:
        raise ValueError(f"Partner with telegram_id {partner_telegram_id} not found")

    if not partner.is_active:
        raise ValueError(f"Partner with telegram_id {partner_telegram_id} is already inactive")

    old_values = {
        "is_active": True,
        "min_topup_toman": partner.min_topup_toman,
        "discount_percent": partner.discount_percent,
    }

    partner.is_active = False
    partner.updated_at = func.now()
    
    await session.flush()

    # Audit the revocation
    audit = PartnerAudit(
        partner_telegram_id=partner_telegram_id,
        admin_telegram_id=admin_telegram_id,
        action_type="revoke",
        old_values=old_values,
        new_values={"is_active": False},
    )
    session.add(audit)

    await session.commit()
    await session.refresh(partner)
    return partner