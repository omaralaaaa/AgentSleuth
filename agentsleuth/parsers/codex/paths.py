"""Resolve evidence paths and build safe per-conversation output folders."""

import hashlib
import re
from pathlib import Path
from ...core.paths import _path_from_stored



def rollout_for_thread(db_path: Path, thread: dict):
    """Resolve stored absolute or relative rollout_path using SQLite's folder."""
    raw = thread.get('rollout_path', '')
    if not raw:
        raise FileNotFoundError('This thread has no rollout_path in the threads table.')
    db_folder = db_path.expanduser().resolve().parent
    stored = _path_from_stored(raw)
    candidates = []
    if stored.is_absolute():
        candidates.append(stored)
        # Allow evidence copied to a different host: keep path after sessions/.
        pieces = re.split(r'[/\\]+', raw)
        indexes = [i for i, name in enumerate(pieces) if name.lower() == 'sessions']
        if indexes:
            candidates.append(db_folder.joinpath(*pieces[indexes[-1]:]))
    else:
        candidates += [db_folder / stored, db_folder.parent / stored]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    checked = '\n'.join('  - ' + str(x) for x in candidates)
    raise FileNotFoundError(f'Rollout not found for {thread.get("title")}\nStored rollout_path: {raw}\nChecked:\n{checked}')

def _safe_component(text, maximum=68):
    # Avoid filename traversal, reserved Windows characters and unsafe controls.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(text))
    value = re.sub(r'\s+', '_', value).strip(' ._')[:maximum]
    return value or 'untitled'

def _result_dir(root: Path, thread: dict):
    # Deterministic path; never use a path supplied inside the evidence as a write destination.
    safe = _safe_component(thread['name'], 40)
    suffix = hashlib.sha256(thread['id'].encode()).hexdigest()[:10]
    return root / f'{safe}_{suffix}'
