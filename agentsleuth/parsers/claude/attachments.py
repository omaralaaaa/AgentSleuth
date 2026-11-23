"""Extract explicit structured Claude media without opening external references."""

import base64
import mimetypes
import re

from .artifacts import MAX_FILE_BYTES, filename
from .records import object_value, string_value


MEDIA_TYPES = {'image', 'document', 'audio', 'file', 'attachment'}
EXTENSIONS = {'image/png': '.png', 'image/jpeg': '.jpg', 'application/pdf': '.pdf'}


def attachment(block, reference, index, artifacts):
    source = object_value(block.get('source'))
    media = string_value(source.get('media_type') or block.get('media_type'))
    ext = EXTENSIONS.get(media) or mimetypes.guess_extension(media.split(';', 1)[0]) or '.bin'
    ext = ext if re.fullmatch(r'\.[A-Za-z0-9]{1,9}', ext) else '.bin'
    recorded_name = string_value(block.get('filename') or block.get('title') or source.get('filename'))
    display_name = filename(recorded_name) if recorded_name else f'{block.get("type", "file")}{ext}'
    result = {'filename': display_name, 'mime': media, 'status': 'reference',
              'suffix': '· attachment reference', 'source': reference, 'block_index': index,
              'saved_path': None}
    if source.get('type') != 'base64':
        return result
    encoded = source.get('data')
    try:
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3):
            raise ValueError('Missing or oversized Base64 attachment')
        blob = base64.b64decode(encoded, validate=True)
        if not blob:
            raise ValueError('Empty Base64 attachment')
        result.update(artifacts.save('attachments', display_name, blob))
        result.update(status='extracted', suffix='· extracted attachment')
    except (ValueError, OSError, RuntimeError) as error:
        result.update(status='unavailable', suffix='· attachment unavailable', error=str(error))
    return result
