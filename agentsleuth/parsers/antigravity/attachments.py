"""Recover uploads explicitly linked to a recorded Antigravity prompt."""

import ntpath
from urllib.parse import unquote, urlsplit

from ...core.artifacts import MAX_FILE_BYTES


def recover_uploads(step, upload_dir, store):
    media = step.get('media')
    if not isinstance(media, list):
        return []
    results = []
    for item in media:
        if not isinstance(item, dict) or not isinstance(uri := item.get('uri'), str):
            continue
        recorded = uri
        local = '://' not in uri
        if uri.lower().startswith('file:'):
            try:
                parsed = urlsplit(uri)
                recorded = unquote(parsed.path)
                local = parsed.netloc.lower() in ('', 'localhost')
            except ValueError:
                continue
        name = ntpath.basename(recorded) or 'Attachment'
        result = dict(filename=name, mime=item.get('mime_type'), uri=uri, saved_path=None,
                      status='reference', suffix='· reference only')
        parent = ntpath.basename(ntpath.dirname(recorded))
        if local and store is not None and upload_dir is not None and parent.lower() == '.user_uploaded':
            try:
                source = upload_dir / name
                if ':' in name or source.resolve() != source or not source.is_file():
                    raise ValueError('Recorded upload is missing from the session')
                with source.open('rb') as stream:
                    blob = stream.read(MAX_FILE_BYTES + 1)
                result.update(store.save('attachments', name, blob))
                result.update(status='extracted', suffix='· extracted copy')
            except (OSError, ValueError, RuntimeError) as error:
                result.update(status='unavailable', suffix='· extraction failed', error=str(error))
        results.append(result)
    return results
