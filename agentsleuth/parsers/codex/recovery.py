"""Recover file contents explicitly recorded by Codex FileChange events."""

import hashlib
import ntpath

from .config import MAX_ATTACHMENT_BYTES
from .paths import _safe_component
from ...core.artifacts import write_session_artifact


def _recover_file_changes(activities, destination):
    """Recover text content recorded in FileChange, without executing it."""
    recovered = []
    for activity in activities:
        if activity['activity_type'] != 'FileChange':
            continue
        for original, change in (activity.get('item', {}).get('changes') or {}).items():
            if not isinstance(change, dict):
                continue
            content = change.get('content')
            if not isinstance(content, str):
                continue
            operation = str(change.get('type', 'unknown')).lower()
            original = str(original)
            basename = ntpath.basename(original.replace('/', '\\'))
            name = _safe_component(basename, 90)
            # For partial updates never suggest that this was the whole final file.
            if operation not in {'add', 'create', 'rewrite'}:
                name += '.logged-change.txt'
            token = hashlib.sha256((original + '\0' + str(activity['ordinal'])).encode()).hexdigest()[:10]
            blob = content.encode('utf-8')
            if len(blob) > MAX_ATTACHMENT_BYTES:
                continue
            digest = hashlib.sha256(blob).hexdigest()
            new_path = write_session_artifact(
                destination, 'recovered_files', f'{token}_{name}', blob,
                alternate_name=f'{token}_{digest[:8]}_{name}',
            )
            recovered.append({
                'original_path': original, 'saved_path': str(new_path),
                'operation': operation, 'size_bytes': len(blob),
                'sha256': digest, 'ordinal': activity['ordinal'],
                'note': 'Rebuilt from logged text; bytes on original disk are not verified.'
            })
    return recovered
