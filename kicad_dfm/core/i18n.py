import builtins
import gettext
import os

DOMAIN = "kicad_hqdfm_plugin"

_translation = gettext.NullTranslations()


def locale_dir():
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "language", "locale")


def normalize_locale(language):
    if not language:
        return "zh_CN"
    value = str(language).replace("-", "_")
    lower_value = value.lower()
    if lower_value.startswith("zh") or "中文" in value or "chinese" in lower_value:
        return "zh_CN"
    if lower_value.startswith("en") or "english" in lower_value or "英语" in value or "英文" in value:
        return "en"
    return value


def init_i18n(language=None, wx_module=None):
    global _translation
    languages = [normalize_locale(language)] if language else None
    try:
        _translation = gettext.translation(DOMAIN, locale_dir(), languages=languages, fallback=True)
    except Exception:
        _translation = gettext.NullTranslations()
    if wx_module is not None:
        wx_module.Locale.AddCatalogLookupPathPrefix(locale_dir())
        existing_locale = wx_module.GetLocale()
        if existing_locale is not None:
            existing_locale.AddCatalog(DOMAIN)
    builtins.__dict__["_"] = _
    return _


def _(message):
    return _translation.gettext(message)
