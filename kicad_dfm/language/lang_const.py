from __future__ import annotations

from typing import Any


def get_supported_language() -> tuple[Any, ...]:
    import wx

    try:
        return (
            wx.LANGUAGE_ENGLISH,
            wx.LANGUAGE_JAPANESE_JAPAN,
            wx.LANGUAGE_CHINESE_SIMPLIFIED,
        )
    except AttributeError:
        return (
            wx.LANGUAGE_ENGLISH,
            wx.LANGUAGE_CHINESE_SIMPLIFIED,
        )


def code_to_wx() -> dict[str, Any]:
    import wx

    try:
        return {
            "en": wx.LANGUAGE_ENGLISH,
            "ja": wx.LANGUAGE_JAPANESE_JAPAN,
            "zh_CN": wx.LANGUAGE_CHINESE_SIMPLIFIED,
        }
    except AttributeError:
        return {
            "en": wx.LANGUAGE_ENGLISH,
            "zh_CN": wx.LANGUAGE_CHINESE_SIMPLIFIED,
        }


def fool_translation() -> list[Any]:
    import wx

    _ = wx.GetTranslation
    return [_("English"), _("Japanese"), _("Chinese")]
