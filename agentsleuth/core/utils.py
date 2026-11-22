"""Small shared helpers used by the parser and UI."""

import hashlib
import json
from pathlib import Path


def short(value, max_len=160):
    value = str(value or "").replace("\r", " ").replace("\n", " ")
    return value[:max_len] + ("…" if len(value) > max_len else "")

def safe_text(value):
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(value, ensure_ascii=False, indent=2)

def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
