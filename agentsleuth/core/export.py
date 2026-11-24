"""Manage the export preference and isolate generated evidence by agent and session."""

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile


EXPORT_NAME = 'AgentSleuth_Export'
AGENT_DIRECTORIES = ('Codex', 'OpenCode', 'Claude', 'Antigravity')
SESSION_OWNER = '.agentsleuth-session.json'
INVALID_TITLE = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f\ud800-\udfff]')
RESERVED_NAME = re.compile(r'(?:CON|CONIN\$|CONOUT\$|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])\Z', re.IGNORECASE)


def preference_path():
    config = os.environ.get('LOCALAPPDATA') if os.name == 'nt' else os.environ.get('XDG_CONFIG_HOME')
    return (Path(config) if config else Path.home() / '.config') / 'AgentSleuth' / 'export.json'


def read_export_root(script_directory, preference):
    try:
        saved = json.loads(preference.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return script_directory / EXPORT_NAME
    if not isinstance(saved, str) or not Path(saved).is_absolute():
        raise ValueError('The saved export directory must be an absolute path')
    return Path(saved)


def save_export_root(preference, root):
    preference.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', encoding='utf-8', dir=preference.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(str(root), stream)
        temporary.replace(preference)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_export_root(root):
    """Check the configured path without creating it or its agent directories."""
    target = Path(root).expanduser().resolve()
    for directory in (target, *target.parents):
        if directory.exists():
            if not directory.is_dir():
                raise NotADirectoryError(str(directory))
            break


def _folder_title(title):
    name = INVALID_TITLE.sub('_', str(title or '').strip()).strip(' .')
    name = name.encode('utf-8')[:120].decode('utf-8', errors='ignore').rstrip(' .')
    if RESERVED_NAME.fullmatch(name.split('.', 1)[0].rstrip(' ')):
        name = '_' + name
    return name or 'Unnamed_Conversation'


def session_owner_data(session_id):
    return json.dumps(str(session_id)).encode('utf-8')


def owns_session_directory(directory, session_id):
    marker = directory / SESSION_OWNER
    owner = session_owner_data(session_id)
    try:
        if marker.resolve() == marker and marker.is_file() and marker.stat().st_size == len(owner):
            with marker.open('rb') as stream:
                return stream.read(len(owner) + 1) == owner
    except (OSError, RuntimeError):
        pass
    return False


class ExportSession:
    def __init__(self, root, agent, session_id, title=None):
        if agent not in AGENT_DIRECTORIES:
            raise ValueError(f'Unknown export agent {agent!r}')
        self.parent = Path(root).expanduser().resolve() / agent
        self.session_id = str(session_id)
        self.title = _folder_title(title)
        self.selected_directory = None

    @classmethod
    def from_thread(cls, root, agent, thread):
        return cls(root, agent, thread['id'], thread.get('export_title', thread.get('name')))

    @property
    def directory(self):
        if self.selected_directory is not None:
            return self.selected_directory
        if not self.parent.is_dir() or self.parent.resolve() != self.parent:
            return self.parent / self.title
        try:
            siblings = sorted(self.parent.iterdir())
        except FileNotFoundError:
            return self.parent / self.title
        suffix = re.sub(r'[^a-zA-Z0-9_-]', '', self.session_id)[:8]
        if not suffix:
            suffix = hashlib.sha256(self.session_id.encode('utf-8', errors='surrogatepass')).hexdigest()[:8]
        prefix = f'{self.title} ({suffix}'
        pattern = re.compile(re.escape(prefix.casefold()) + r'(?:-\d+)?\)\Z')
        names = set()
        for path in siblings:
            key = path.name.casefold()
            names.add(key)
            if key == self.title.casefold() or pattern.fullmatch(key):
                if owns_session_directory(path, self.session_id):
                    return path
        candidate = self.title
        counter = 1
        while candidate.casefold() in names:
            numbered = f'-{counter}' if counter > 1 else ''
            candidate = f'{prefix}{numbered})'
            counter += 1
        return self.parent / candidate
