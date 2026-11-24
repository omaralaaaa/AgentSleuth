"""Interpret OpenCode FilePart URLs without dereferencing recorded paths."""

import base64
import mimetypes
import ntpath
import re
from urllib.parse import unquote, unquote_to_bytes

from ...core.artifacts import MAX_FILE_BYTES


def _decode(data, encoded):
    if encoded:
        if len(data) > 4 * ((MAX_FILE_BYTES + 2) // 3):
            raise ValueError('Attachment exceeds the extraction size limit')
        return base64.b64decode(data, validate=True)
    if len(data) > 3 * MAX_FILE_BYTES:
        raise ValueError('Attachment exceeds the extraction size limit')
    # Decode bounded chunks, keeping each percent escape in one chunk.
    blob = bytearray()
    start = 0
    while start < len(data):
        end = min(start + 65536, len(data))
        if end < len(data):
            tail = data.rfind('%', end - 2, end)
            if tail >= start:
                end = tail
        chunk = data[start:end]
        if re.search(r'%(?![0-9A-Fa-f]{2})', chunk):
            raise ValueError('Invalid percent escape in attachment')
        blob.extend(unquote_to_bytes(chunk))
        if len(blob) > MAX_FILE_BYTES:
            raise ValueError('Attachment exceeds the extraction size limit')
        start = end
    return blob


def parse_upload(part, store, *, fallback_filename=None):
    url = part.get('url')
    url = url if isinstance(url, str) else ''
    embedded = url[:5].lower() == 'data:'
    source = part.get('source')
    path = source.get('path') if isinstance(source, dict) else None
    name = part.get('filename') or path or fallback_filename
    if not name and url and not embedded:
        name = unquote(url.split('?', 1)[0].split('#', 1)[0])
    name = ntpath.basename(name) if isinstance(name, str) else ''
    result = dict(filename=name or 'Attachment', mime=part.get('mime'), saved_path=None,
                  status='reference', suffix='· reference only')
    if not embedded:
        return result
    header, separator, data = url.partition(',')
    params = header[5:].split(';')
    result['mime'] = result['mime'] or params[0] or 'text/plain'
    if not name:
        mime = result['mime'] if isinstance(result['mime'], str) else ''
        result['filename'] = 'Attachment' + (mimetypes.guess_extension(mime) or '.bin')
    try:
        if not separator:
            raise ValueError('Incomplete data URI')
        if store is None:
            result.update(status='embedded', suffix='· embedded, no output directory selected')
            return result
        blob = _decode(data, params[-1].lower() == 'base64')
        result.update(store.save('attachments', result['filename'], blob))
        result.update(status='extracted', suffix='· extracted copy')
    except (OSError, RuntimeError, ValueError) as error:
        result.update(status='unavailable', suffix='· extraction failed', error=str(error))
    return result
