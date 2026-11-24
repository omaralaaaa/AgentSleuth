"""Small shared helpers used by the parser and UI."""

import json


def short(value, max_len=160):
    value = str(value or "").replace("\r", " ").replace("\n", " ")
    return value[:max_len] + ("…" if len(value) > max_len else "")

def safe_text(value):
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2)
