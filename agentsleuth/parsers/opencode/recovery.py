"""Recover complete content recorded by OpenCode file tools."""

import ntpath

from .attachments import parse_upload


def _object(value):
    return value if isinstance(value, dict) else {}


def tool_attachments(execution, store):
    """Reuse file-part extraction for embedded attachments on tool results."""
    parts = execution.get('attachments')
    if not isinstance(parts, list):
        return
    fallback = None
    if execution.get('tool') == 'read' and len(parts) == 1:
        fallback = _object(execution.get('arguments')).get('filePath')
    for part in parts:
        if isinstance(part, dict) and part.get('type') == 'file':
            upload = parse_upload(part, store, fallback_filename=fallback)
            upload['attachment_part_id'] = part.get('id')
            yield upload


def recover_file(execution, store):
    tool = execution.get('tool')
    if tool not in ('write', 'edit') or execution.get('status') != 'completed':
        return None
    args = _object(execution.get('arguments'))
    metadata = _object(execution.get('metadata'))
    diff = _object(metadata.get('filediff'))
    if tool == 'write':
        path = metadata.get('filepath') or args.get('filePath')
        content = args.get('content')
    else:
        path = diff.get('file') or args.get('filePath')
        content = diff.get('after')
    if not isinstance(path, str) or not path.strip():
        return None
    result = dict(original_path=path, filename=ntpath.basename(path) or 'File', saved_path=None,
                  operation=tool, status='reference', suffix='· recorded path')
    if store is None or not isinstance(content, str):
        return result
    try:
        result.update(store.save('recovered_files', result['filename'], content.encode('utf-8')))
        result.update(status='recovered', suffix='· copied recorded file content')
    except (OSError, RuntimeError, ValueError) as error:
        result.update(status='unavailable', suffix='· copy unavailable', error=str(error))
    return result
