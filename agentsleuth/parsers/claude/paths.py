"""Resolve project transcripts within the selected Claude evidence tree."""

import os
import re
from collections import defaultdict
from pathlib import Path


SESSION_ID = re.compile(r'[A-Za-z0-9_-]{1,160}\Z')


def project_component(project):
    return re.sub(r'[^A-Za-z0-9-]', '-', project)


def local_directory(path):
    try:
        return path.resolve() == path and path.is_dir()
    except (OSError, RuntimeError, ValueError):
        return False


def within(path, root):
    """Return a resolved evidence file when it stays inside its evidence root."""
    try:
        resolved = path.resolve(strict=True)
        if resolved.is_relative_to(root) and resolved.is_file():
            return resolved
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def transcript_index(projects, ids):
    """Index filenames in one walk and avoid following directories outside projects."""
    matches = defaultdict(set)
    names = {f'{sid}.jsonl': sid for sid in ids}
    if not names or not local_directory(projects):
        return matches
    for parent, directories, files in os.walk(projects):
        folder = Path(parent)
        directories[:] = [name for name in directories if local_directory(folder / name)]
        for name in files:
            if name in names and (path := within(folder / name, projects)) is not None:
                matches[names[name]].add(path)
    return matches


def resolve_session(projects, session_id, project_paths, index=None):
    if not SESSION_ID.fullmatch(session_id):
        raise ValueError('Invalid Claude Code session identifier')
    matches = (index if index is not None else transcript_index(projects, [session_id])).get(session_id, ())
    preferred = {projects / project_component(project) / f'{session_id}.jsonl' for project in project_paths}
    expected = [path for path in matches if path in preferred]
    candidates = expected or sorted(matches)
    if not candidates:
        raise FileNotFoundError(f'Claude Code session transcript is missing ({session_id})')
    if len(candidates) != 1:
        locations = ', '.join(str(path.relative_to(projects)) for path in sorted(candidates))
        raise ValueError(f'Multiple Claude Code transcripts match this session: {locations}')
    return candidates[0]
