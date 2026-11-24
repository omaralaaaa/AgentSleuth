"""Read Antigravity session scratch files as separate evidence artifacts."""

import codecs
import os
import stat
from pathlib import Path

from ...core.artifacts import MAX_FILE_BYTES


PREVIEW_BYTES = 64 * 1024
SKIP_DIRECTORIES = {'.git', '.hg', '.svn', '__pycache__', 'node_modules', '.venv', 'venv', '.cache'}


def _local_stat(path):
    try:
        info = path.lstat()
        if (path.resolve() == path and not stat.S_ISLNK(info.st_mode)
                and not getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            return info
    except (OSError, RuntimeError):
        pass
    return None


def scratch_directory(session):
    if session is not None:
        directory = session / 'scratch'
        info = _local_stat(directory)
        if info is not None and stat.S_ISDIR(info.st_mode):
            return directory
    return None


def _preview(blob, truncated):
    encoding = 'utf-16' if blob.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else 'utf-8-sig'
    try:
        text = codecs.getincrementaldecoder(encoding)().decode(blob, final=not truncated)
    except UnicodeError:
        return None
    if any(ord(char) < 32 and char not in '\t\r\n\f' for char in text):
        return None
    return text


def recover_scratch(directory, store, progress=None):
    """Yield a record for each local regular file. Keep memory use bounded per file."""
    if directory is None:
        return
    count = 0
    for parent, subdirs, names in os.walk(directory, followlinks=False):
        folder = Path(parent)
        subdirs[:] = sorted(name for name in subdirs if name.casefold() not in SKIP_DIRECTORIES
                            and (info := _local_stat(folder / name)) is not None
                            and stat.S_ISDIR(info.st_mode))
        for name in sorted(names):
            source = folder / name
            info = _local_stat(source)
            if info is None or not stat.S_ISREG(info.st_mode):
                continue
            count += 1
            if progress and count % 25 == 0:
                progress(f'Reading Antigravity scratch files · {count:,} files')
            relative = source.relative_to(directory).as_posix()
            record = dict(filename=relative, relative_path=relative, original_path=str(source),
                          size_bytes=info.st_size, saved_path=None, status='reference',
                          suffix='· scratch file')
            export = store is not None and info.st_size <= MAX_FILE_BYTES
            try:
                with source.open('rb') as stream:
                    data = stream.read((MAX_FILE_BYTES if export else PREVIEW_BYTES) + 1)
                sample = data[:PREVIEW_BYTES]
                record['preview_truncated'] = max(info.st_size, len(data)) > PREVIEW_BYTES
                record['preview'] = _preview(sample, record['preview_truncated'])
                if store is not None:
                    if not export:
                        raise ValueError('File exceeds the extraction size limit')
                    record.update(store.save('scratch', relative, data))
                    record.update(status='recovered', suffix='· recovered scratch file')
            except (OSError, RuntimeError, ValueError) as error:
                record.update(status='unavailable', suffix='· scratch copy unavailable', error=str(error))
            yield record
