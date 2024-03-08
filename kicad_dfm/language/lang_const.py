from .constraint import CODE_TO_NAME, ENGLISH, DEFAULT_LANG, LANG_DOMAIN

try:
    from wx import LANGUAGE_JAPANESE_JAPAN
except:
    CODE_TO_NAME = {"en": "English", "zh_CN": "Chinese"}


def get_supported_language():
    import wx

    try:
        # NOTE - LANGUAGE_JAPANESE_JAPAN is not available until Kicad 6.0
        return (
            wx.LANGUAGE_ENGLISH,
            wx.LANGUAGE_JAPANESE_JAPAN,
            wx.LANGUAGE_CHINESE_SIMPLIFIED,
        )
    except:
        return (
            wx.LANGUAGE_ENGLISH,
            wx.LANGUAGE_CHINESE_SIMPLIFIED,
        )


def code_to_wx():
    import wx

    try:
        return {
            "en": wx.LANGUAGE_ENGLISH,
            "ja": wx.LANGUAGE_JAPANESE_JAPAN,
            "zh_CN": wx.LANGUAGE_CHINESE_SIMPLIFIED,
        }
    except:
        return {
            "en": wx.LANGUAGE_ENGLISH,
            "zh_CN": wx.LANGUAGE_CHINESE_SIMPLIFIED,
        }


def fool_translation():
    # Just for triggering the gettext
    import wx

    _ = wx.GetTranslation
    TRANSLATION = [_("English"), _("Japanese"), _("Chinese")]
    return TRANSLATION
