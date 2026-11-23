"""Build a viewer result from a selected OpenCode session."""

import hashlib
from pathlib import Path

from ...core.artifacts import ArtifactStore
from .attachments import parse_upload
from .database import read_conversation
from .reconstruction import reconstruct


def reconstruct_from_thread(path, thread, output_root=None, progress=None):
    session_id = thread['id']
    message_rows, part_rows, messages_with_parts = read_conversation(path, session_id, progress)
    if progress:
        progress('Reconstructing OpenCode timeline…')
    messages, turns, summary = reconstruct(
        session_id, message_rows, part_rows, progress, messages_with_parts=messages_with_parts
    )
    store = None
    if output_root is not None:
        key = hashlib.sha256(session_id.encode()).hexdigest()[:24]
        store = ArtifactStore(Path(output_root).expanduser().resolve() / 'OpenCode' / key)
    attachments = []
    failures = []
    parts = {part['id']: part for msg in messages for part in msg['parts'] if part['type'] == 'file'}
    for turn in turns:
        prompts = {}
        for entry in turn['entries']:
            if entry['event_type'] == 'user_prompt':
                prompts.setdefault(entry['message_id'], entry)
        for entry in turn['entries']:
            if entry['event_type'] != 'file_attachment':
                continue
            upload = parse_upload(parts[entry['part_id']]['data'], store)
            upload.update(message_id=entry['message_id'], part_id=entry['part_id'], ordinal=entry['ordinal'])
            entry['attachments'] = [upload]
            entry['file_links'] = [upload]
            if entry['message_id'] in prompts:
                prompts[entry['message_id']].setdefault('file_links', []).append(upload)
            entry.pop('evidence', None)  # Raw SQLite evidence remains in entry['raw'].
            attachments.append(upload)
            if upload['status'] == 'unavailable':
                failures.append(upload)
    summary['attachments'] = sum(a['status'] == 'extracted' for a in attachments)
    return {'thread': thread, 'session': {'session_id': session_id}, 'source_path': str(path),
            'attachments': attachments, 'attachment_failures': failures,
            'output_directory': str(store.directory) if store else None,
            'messages': messages, 'turns': turns, 'summary': summary}
