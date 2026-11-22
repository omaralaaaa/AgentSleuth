"""Metadata fields shared by Codex event and attachment records."""

import json

def get_turn(record):
    payload = record.get("payload") or {}
    passthrough = payload.get("internal_chat_message_metadata_passthrough") or {}
    return payload.get("turn_id") or passthrough.get("turn_id") or ""


def prompt_permissions(payload):
    """Describe only fields recorded in this turn's permission snapshot."""
    def field(value, key):
        return value.get(key) if isinstance(value, dict) else value

    active = field(payload.get('active_permission_profile'), 'id')
    sandbox = payload.get('sandbox_policy')
    profile = payload.get('permission_profile')
    mode = field(sandbox, 'type')
    parts = [str(v) for v in (active, mode) if v]
    if not mode and isinstance(profile, dict):
        filesystem = field(profile.get('file_system'), 'type')
        if filesystem:
            parts.append(f'Filesystem: {filesystem}')
        elif profile.get('type') and profile['type'] != 'managed':
            parts.append(str(profile['type']))
    network = profile.get('network') if isinstance(profile, dict) else None
    if network is None and isinstance(sandbox, dict) and isinstance(sandbox.get('network_access'), bool):
        network = 'enabled' if sandbox['network_access'] else 'restricted'
    if network is not None:
        parts.append(f'Network: {network}')
    approval = payload.get('approval_policy')
    if approval is not None:
        if isinstance(approval, dict):
            approval = json.dumps(approval, ensure_ascii=False)
        parts.append(f'Approval: {approval}')
    return ' · '.join(parts) or 'Not recorded'
