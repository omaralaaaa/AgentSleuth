"""Recover explicitly recorded file contents and linked file-history backups."""

import re

from .artifacts import MAX_FILE_BYTES, decode_base64, filename
from .paths import local_directory, within
from .records import object_value, string_value


def _save(result, content, artifacts, category='recovered_files'):
    try:
        if len(content) > MAX_FILE_BYTES:
            raise ValueError('File exceeds the extraction size limit')
        blob = content.encode('utf-8') if isinstance(content, str) else content
        result.update(artifacts.save(category, result['filename'], blob))
    except (ValueError, OSError, RuntimeError) as error:
        result.update(error=str(error), suffix=result['suffix'] + ' · copy unavailable')
    return result


def _binary_read_content(recorded_file, kind):
    if recorded_file.get('truncated') is True:
        raise ValueError('Recorded file content is truncated')
    blob = decode_base64(recorded_file['base64'])
    size = recorded_file.get('originalSize')
    if size is not None and (type(size) is not int or size != len(blob)):
        raise ValueError('Recorded bytes do not match the original file size')
    if kind == 'pdf':
        if b'%PDF-' not in blob[:1024]:
            raise ValueError('Recorded PDF header is missing')
        if size is None and not blob.rstrip().endswith(b'%%EOF'):
            raise ValueError('Recorded PDF end marker is missing')
    return blob


def operation(execution, metadata, artifacts):
    tool = string_value(execution['tool']).casefold()
    if tool not in {'write', 'edit', 'read', 'multiedit'}:
        return None
    args = object_value(execution['arguments'])
    read_file = object_value(metadata.get('file'))
    original = (string_value(metadata.get('filePath')) or string_value(read_file.get('filePath'))
                or string_value(args.get('file_path')))
    if not original:
        return None
    status = execution['status']
    result = {'original_path': original, 'filename': filename(original), 'saved_path': None,
              'operation': tool, 'status': status, 'suffix': '· recorded path'}
    if tool == 'read':
        if status != 'completed':
            return result
        if 'base64' in read_file and metadata.get('truncated') is not True:
            kind = metadata.get('type')
            try:
                blob = _binary_read_content(read_file, kind)
            except ValueError as error:
                result.update(error=str(error), suffix='· recorded file copy unavailable')
                return result
            result['suffix'] = '· copied recorded PDF' if kind == 'pdf' else '· copied recorded Read bytes'
            return _save(result, blob, artifacts)
        content = read_file.get('content')
        if (metadata.get('type') == 'text' and isinstance(content, str)
                and read_file.get('startLine') == 1 and isinstance(read_file.get('totalLines'), int)
                and read_file.get('numLines') == read_file['totalLines']):
            result['suffix'] = '· copied recorded Read content'
            return _save(result, content, artifacts)
        return result
    completed = status == 'completed'
    content = metadata.get('content') if completed else None
    if tool == 'write' and not isinstance(content, str) and not metadata.get('userModified'):
        content = args.get('content')
    if tool in {'edit', 'multiedit'} and completed and not isinstance(content, str):
        content = metadata.get('modifiedFile')
        if not isinstance(content, str) and tool == 'edit' and not metadata.get('userModified'):
            before = metadata.get('originalFile')
            old = metadata.get('oldString', args.get('old_string'))
            new = metadata.get('newString', args.get('new_string'))
            replace_all = metadata.get('replaceAll', args.get('replace_all')) is True
            if isinstance(before, str) and isinstance(old, str) and old and isinstance(new, str):
                count = before.count(old)
                if count == 1 or (count and replace_all):
                    content = before.replace(old, new)
    if not isinstance(content, str):
        return result
    result['suffix'] = '· rebuilt from recorded content' if completed else '· proposed write'
    return _save(result, content, artifacts)


def snapshot_files(reference, session_id, artifacts):
    snapshot = object_value(reference['raw'].get('snapshot'))
    tracked = object_value(snapshot.get('trackedFileBackups'))
    root = artifacts.evidence_root / 'file-history' / session_id
    for original, value in tracked.items():
        backup = object_value(value)
        name = string_value(backup.get('backupFileName'))
        result = {'original_path': original, 'filename': filename(original), 'saved_path': None,
                  'operation': 'snapshot', 'source': reference,
                  'suffix': '· snapshot backup reference'}
        path = None
        if name and re.fullmatch(r'[A-Za-z0-9_.@-]+', name) and local_directory(root):
            path = within(root / name, root)
        if path is not None:
            try:
                with path.open('rb') as handle:
                    content = handle.read(MAX_FILE_BYTES + 1)
                result.update(backup_source=str(path), suffix='· copied snapshot backup')
                _save(result, content, artifacts)
            except OSError as error:
                result.update(error=str(error), suffix='· snapshot backup unavailable')
        yield result
