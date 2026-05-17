import json
import os
from pathlib import Path
from typing import Optional

_translations: dict[str, dict[str, str]] = {}

def _load(lang: str) -> dict[str, str]:
    if lang in _translations:
        return _translations[lang]
    path = Path(__file__).parent / f"{lang}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            _translations[lang] = json.load(f)
    else:
        _translations[lang] = {}
    return _translations[lang]


def t(key: str, lang: str = "ru", **fmt) -> str:
    d = _load(lang)
    text = d.get(key, key)
    if fmt:
        try:
            text = text.format(**fmt)
        except KeyError:
            pass
    return text


def user_lang_key(user_id: int) -> str:
    return f"user:lang:{user_id}"
