"""Metadata fields shared by Codex event and attachment records."""


def get_turn(record):
    payload = record.get("payload") or {}
    passthrough = payload.get("internal_chat_message_metadata_passthrough") or {}
    return payload.get("turn_id") or passthrough.get("turn_id") or ""
