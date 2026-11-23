"""Resolve evidence paths and build safe per-conversation output folders."""

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
    scope = thread.get('_evidence_root')
    if stored.is_absolute():
        if scope is None:
            candidates.append(stored)
        # Allow evidence copied to a different host: keep path after sessions/.
        pieces = re.split(r'[/\\]+', raw)
        indexes = [i for i, name in enumerate(pieces) if name.lower() in ('sessions', 'archived_sessions')]
        if indexes:
            candidates.append(db_folder.joinpath(*pieces[indexes[-1]:]))
    else:
        candidates += [db_folder / stored, db_folder.parent / stored]
    for candidate in candidates:
        if scope is not None and not candidate.resolve().is_relative_to(scope):
            continue
        if candidate.is_file():
            return candidate.resolve()
    checked = '\n'.join('  - ' + str(x) for x in candidates)
    raise FileNotFoundError(f'Rollout not found for {thread.get("title")}\nStored rollout_path: {raw}\nChecked:\n{checked}')

def _safe_component(text, maximum=68):
    # Avoid filename traversal, reserved Windows characters and unsafe controls.
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(text))
    value = re.sub(r'\s+', '_', value).strip(' ._')[:maximum]
    return value or 'untitled'
