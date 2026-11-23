"""Write bounded, non-overwriting copies of embedded evidence."""

import hashlib
import os
import re
from contextlib import suppress
from threading import RLock

from .export import ExportSession, SESSION_OWNER, owns_session_directory, session_owner_data


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024
_WRITE_LOCK = RLock()


class _DirectoryClaimed(Exception):
    pass


def validate_artifact_destination(target, protected=()):
    if target.resolve() != target or any(target.is_relative_to(path) for path in protected):
        raise ValueError('Choose a results directory outside protected evidence paths')


def _check_existing(target, blob):
    if not target.is_file() or target.stat().st_size != len(blob) or target.read_bytes() != blob:
        raise ValueError('An existing results file has different evidence')


def _write_file(target, blob, created, protected):
    validate_artifact_destination(target, protected)
    try:
        stream = target.open('xb')
    except FileExistsError:
        validate_artifact_destination(target, protected)
        _check_existing(target, blob)
    else:
        with stream:
            created.append((target, os.fstat(stream.fileno())))
            if stream.write(blob) != len(blob):
                raise OSError('Incomplete artifact write')


def write_artifact(target, blob, protected=(), *, owner=None):
    """Save validated bytes and roll back only paths created by this write."""
    blob = memoryview(blob).cast('B')
    with _WRITE_LOCK:
        validate_artifact_destination(target, protected)
        if owner is not None and owner[0].exists() and not owns_session_directory(*owner):
            raise _DirectoryClaimed
        if target.exists():
            _check_existing(target, blob)
            return
        missing = []
        for directory in target.parents:
            if directory.exists():
                break
            missing.append(directory)
        directories, files = {}, []
        try:
            for directory in reversed(missing):
                try:
                    directory.mkdir()
                except FileExistsError:
                    if not directory.is_dir():
                        raise
                else:
                    directories[directory] = directory.lstat()
            new_session = owner is not None and owner[0] in directories
            if owner is not None and not new_session and not owns_session_directory(*owner):
                raise _DirectoryClaimed
            _write_file(target, blob, files, protected)
            if new_session:
                _write_file(owner[0] / SESSION_OWNER, session_owner_data(owner[1]), files, protected)
        except BaseException:
            for path, original in reversed(files):
                with suppress(OSError):
                    if os.path.samestat(path.lstat(), original):
                        path.unlink()
            for directory, original in reversed(directories.items()):
                with suppress(OSError):
                    if os.path.samestat(directory.lstat(), original):
                        directory.rmdir()
            raise


def write_session_artifact(destination, category, name, blob, protected=(), *, alternate_name=None):
    """Choose the conversation folder when the first artifact is saved."""
    session = destination if isinstance(destination, ExportSession) else None
    with _WRITE_LOCK:
        while True:
            directory = session.directory if session is not None else destination
            target = directory / category / name
            if alternate_name:
                validate_artifact_destination(target, protected)
                if target.exists() and target.read_bytes() != blob:
                    target = target.with_name(alternate_name)
            owner = (directory, session.session_id) if session is not None else None
            try:
                write_artifact(target, blob, protected, owner=owner)
            except _DirectoryClaimed:
                session.selected_directory = None
                continue
            if session is not None:
                session.selected_directory = directory
            return target


class ArtifactStore:
    def __init__(self, directory, protected=()):
        self.destination = directory
        self.protected = list(protected)
        self.saved = {}
        self.total_bytes = 0

    @property
    def directory(self):
        return self.destination.directory if isinstance(self.destination, ExportSession) else self.destination

    def save(self, category, name, blob):
        if len(blob) > MAX_FILE_BYTES:
            raise ValueError('File exceeds the extraction size limit')
        digest = hashlib.sha256(blob).hexdigest()
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', name)[:100].strip(' .') or 'file'
        directory = self.directory / category
        target = directory / f'{digest[:24]}_{safe_name}'
        if target in self.saved:
            validate_artifact_destination(target, self.protected)
            return self.saved[target]
        if self.total_bytes + len(blob) > MAX_TOTAL_BYTES:
            raise ValueError('Session exceeds the extraction size limit')
        target = write_session_artifact(self.destination, category, target.name, blob, self.protected)
        result = {'saved_path': str(target), 'size_bytes': len(blob), 'sha256': digest}
        self.saved[target] = result
        self.total_bytes += len(blob)
        return result
