"""Discover agent evidence by path without opening databases or transcripts."""

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path


ANTIGRAVITY_FOLDERS = ('antigravity', 'antigravity-ide', 'antigravity-cli')
AGENT_FOLDERS = ('.codex', '.claude', 'opencode', *ANTIGRAVITY_FOLDERS)


@dataclass(frozen=True)
class Finding:
    agent: str
    path: Path
    source: Path | None
    status: str


def _folders(directory, files, subdirs):
    name = directory.name.casefold()
    states = [(int(m[1]), file) for file in files
              if (m := re.fullmatch(r'state_(\d+)\.sqlite', file))]
    if states or name == '.codex':
        source = files[max(states)[1]] if states else None
        yield Finding('Codex', directory, source, source.name if source else 'Missing state database')
    if 'opencode.db' in files or name == 'opencode':
        source = files.get('opencode.db')
        yield Finding('OpenCode', directory, source, 'opencode.db' if source else 'Missing opencode.db')
    if name == '.claude' or ('history.jsonl' in files and 'projects' in subdirs):
        source = files.get('history.jsonl')
        yield Finding('Claude Code', directory, source, 'history.jsonl' if source else 'Missing history.jsonl')
    if name in ANTIGRAVITY_FOLDERS or 'conversation_summaries.db' in files:
        source = files.get('conversation_summaries.db')
        if source:
            yield Finding('Antigravity', directory, source, source.name)
        elif subdirs.intersection(('brain', 'conversations')):
            yield Finding('Antigravity', directory, directory, 'Discover sessions on open')
        else:
            yield Finding('Antigravity', directory, None, 'Missing session evidence')


def live_roots():
    home = Path.home()
    profiles = {home}
    if os.name == 'nt':
        users = Path(os.environ.get('SystemDrive', 'C:') + '/Users')
        try:
            profiles.update(users.iterdir())
        except OSError:
            pass
    for profile in sorted(profiles):
        for rel in ('.codex', '.claude', '.local/share/opencode', 'AppData/Local/opencode',
                    'AppData/Roaming/opencode'):
            yield profile / rel
        for name in ANTIGRAVITY_FOLDERS:
            yield profile / '.gemini' / name
    for var, suffix in [('CODEX_HOME', ''), ('CLAUDE_CONFIG_DIR', ''), ('XDG_DATA_HOME', 'opencode')]:
        if os.environ.get(var):
            yield Path(os.environ[var]) / suffix


def scan(roots, cancelled, progress, *, known_locations=False):
    found = {}
    skipped = visited = 0
    starts = set(roots)
    pending = list(starts)
    while pending and not cancelled.is_set():
        directory = pending.pop()
        try:
            info = directory.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                continue
            files = {}
            children = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    if cancelled.is_set():
                        break
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        children.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        key = entry.name.casefold()
                        if key in ('opencode.db', 'conversation_summaries.db', 'history.jsonl') or key.startswith('state_'):
                            if not getattr(entry.stat(follow_symlinks=False), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                                files[key] = Path(entry.path)
            matches = list(_folders(directory, files, {p.name.casefold() for p in children}))
            for hit in matches:
                found[(hit.agent, hit.path)] = hit
            agent_root = directory.name.casefold() in AGENT_FOLDERS
            if not known_locations and not (agent_root and matches):
                pending.extend(children)
            visited += 1
            if visited % 100 == 0:
                progress(visited, len(found))
        except (FileNotFoundError, NotADirectoryError):
            continue
        except OSError:
            skipped += 1
    return sorted(found.values(), key=lambda f: (f.source is None, f.agent, str(f.path).casefold())), skipped
