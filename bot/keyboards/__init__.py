"""Inline keyboards for admin flows."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core.panels.base import PANEL_TYPE_LABELS_FA, PanelType


def get_panel_type_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for selecting panel type during server registration."""
    buttons = []
    for ptype in (PanelType.PASARGUARD, PanelType.MARZBAN, PanelType.HIDDIFY):
        label = PANEL_TYPE_LABELS_FA[ptype]
        buttons.append(
            [InlineKeyboardButton(text=label, callback_data=f"srv_type_{ptype.value}")]
        )
    buttons.append(
        [InlineKeyboardButton(text="❌ انصراف", callback_data="add_srv_cancel")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_confirm_server_keyboard() -> InlineKeyboardMarkup:
    """Keyboard for confirming server registration after ping test."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تایید و ثبت سرور", callback_data="srv_confirm_save"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ ویرایش اطلاعات", callback_data="srv_edit_restart"
                )
            ],
            [
                InlineKeyboardButton(text="❌ انصراف", callback_data="add_srv_cancel")
            ],
        ]
    )