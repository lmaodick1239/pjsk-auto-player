"""
i18n / Internationalization framework.
Inspired by MAA's i18n system. Supports zh_CN, en_US, ja_JP.

Usage:
    from locale import t, set_lang
    set_lang('ja_JP')
    print(t('play.start'))  # → 'ライブ開始'
"""
import builtins
import importlib.util
import json
import os
import sysconfig
from typing import Dict, Any

_LOCALE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_LANG = 'zh_CN'
_current_lang = _DEFAULT_LANG
_translations: Dict[str, Dict[str, str]] = {}
_fallback: Dict[str, str] = {}


def _load_stdlib_locale():
    """Load the standard-library locale module without shadowing this package."""
    stdlib_dir = sysconfig.get_path("stdlib")
    if not stdlib_dir:
        return None

    path = os.path.join(stdlib_dir, "locale.py")
    if not os.path.exists(path):
        return None

    spec = importlib.util.spec_from_file_location("_stdlib_locale", path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_stdlib_locale = _load_stdlib_locale()
_stdlib_public_names = []
if _stdlib_locale is not None:
    for name in dir(_stdlib_locale):
        if name.startswith("_"):
            continue
        _stdlib_public_names.append(name)
        if name not in globals():
            globals()[name] = getattr(_stdlib_locale, name)


def _load_lang(lang: str) -> Dict[str, str]:
    """Load a locale file, flattening nested keys."""
    path = os.path.join(_LOCALE_DIR, f'{lang}.json')
    if not os.path.exists(path):
        return {}

    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    result: Dict[str, str] = {}

    def flatten(obj: Any, prefix: str = '') -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = f'{prefix}.{k}' if prefix else k
                if isinstance(v, dict):
                    flatten(v, key)
                else:
                        result[key] = builtins.str(v)
        elif isinstance(obj, (str, int, float, bool)):
                    result[prefix] = builtins.str(obj)

    flatten(data)
    return result


def set_lang(lang: str) -> None:
    """Set current language. Loads locale/<lang>.json if available."""
    global _current_lang, _translations, _fallback

    if lang not in _translations:
        _translations[lang] = _load_lang(lang)

    _current_lang = lang

    # Ensure fallback is loaded
    if not _fallback:
        _fallback = _load_lang(_DEFAULT_LANG)


def t(key: str, **kwargs) -> str:
    """
    Get translated string for key.

    Args:
        key: Dot-separated key path (e.g. 'play.start')
        **kwargs: format parameters

    Returns:
        Translated string, or key itself if not found.
    """
    global _fallback

    # Lazy load fallback
    if not _fallback:
        _fallback = _load_lang(_DEFAULT_LANG)

    # Try current language
    if _current_lang in _translations:
        text = _translations[_current_lang].get(key)
    else:
        text = None

    # Fallback to default
    if text is None:
        text = _fallback.get(key, key)

    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass

    return text


def get_available_langs() -> list:
    """Get list of available language codes."""
    langs = []
    for f in os.listdir(_LOCALE_DIR):
        if f.endswith('.json') and not f.startswith('_'):
            langs.append(f[:-5])
    return sorted(langs)


__all__ = sorted(set(_stdlib_public_names + [
    't',
    'set_lang',
    'get_available_langs',
]))


# Auto-load default on import
_fallback = _load_lang(_DEFAULT_LANG)
