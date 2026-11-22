"""Recover file contents explicitly recorded by Codex FileChange events."""

import hashlib
import ntpath
from pathlib import Path

from .config import MAX_ATTACHMENT_BYTES
from .paths import _safe_component


def _recover_file_changes(activities, extracted_dir: Path):
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
            new_path = extracted_dir / 'recovered_files' / f'{token}_{name}'
            new_path.parent.mkdir(parents=True, exist_ok=True)
            blob = content.encode('utf-8')
            if len(blob) > MAX_ATTACHMENT_BYTES:
                continue
            if new_path.exists():
                if new_path.read_bytes() != blob:
                    new_path = new_path.with_name(f'{token}_{hashlib.sha256(blob).hexdigest()[:8]}_{name}')
            if not new_path.exists():
                new_path.write_bytes(blob)
            recovered.append({
                'original_path': original, 'saved_path': str(new_path),
                'operation': operation, 'size_bytes': len(blob),
                'sha256': hashlib.sha256(blob).hexdigest(), 'ordinal': activity['ordinal'],
                'note': 'Rebuilt from logged text; bytes on original disk are not verified.'
            })
    return recovered
