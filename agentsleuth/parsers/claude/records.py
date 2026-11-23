"""Read Claude JSONL records and retain their source positions."""

import json
from datetime import datetime, timezone


def object_value(value):
    return value if isinstance(value, dict) else {}


def string_value(value):
    return value if isinstance(value, str) else ''


def records(path):
    with path.open('rb') as stream:
        offset = 0
        for number, line in enumerate(stream, 1):
            position = offset
            offset += len(line)
            if not line.strip():
                continue
            try:
                raw = json.loads(line.decode('utf-8-sig'))
            except (ValueError, RecursionError):
                raw = None
            yield {'source_path': str(path), 'line_number': number, 'byte_offset': position,
                   'raw': raw if isinstance(raw, dict) else None}


def timestamp_label(value):
    try:
        if isinstance(value, str):
            time = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if time.tzinfo is None:
                return value
            time = time.astimezone(timezone.utc)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            time = datetime.fromtimestamp(value / 1000, timezone.utc)
        else:
            return ''
        return time.isoformat(sep=' ', timespec='milliseconds').replace('+00:00', ' UTC')
    except (ValueError, OverflowError, OSError):
        return string_value(value)
