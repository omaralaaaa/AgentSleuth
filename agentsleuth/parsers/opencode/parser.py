"""Build a viewer result from a selected OpenCode session."""

import json

from ...core.artifacts import ArtifactStore
from ...core.export import ExportSession
from .attachments import parse_upload
from .database import read_conversation
from .recovery import recover_file, tool_attachments
from .reconstruction import reconstruct


def _permission_label(raw):
    """Summarize stored session rules without inferring the policy for any prompt."""
    try:
        rules = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        rules = None
    if not isinstance(rules, list):
        return 'Not recorded'
    effects = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if all(isinstance(rule.get(key), str) for key in ('permission', 'pattern')):
            effects.append(rule.get('action'))
        elif all(isinstance(rule.get(key), str) for key in ('action', 'resource')):
            effects.append(rule.get('effect'))
    actions = ', '.join(action for action in ('allow', 'ask', 'deny') if action in effects)
    return f'Session rules ({actions})' if actions else 'Not recorded'


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
        store = ArtifactStore(ExportSession.from_thread(output_root, 'OpenCode', thread))
    attachments = []
    failures = []
    recovered_files = []
    parts = {part['id']: part for msg in messages for part in msg['parts'] if part['type'] == 'file'}
    session = {key.lower(): value for key, value in thread.get('raw', {}).items()}
    permission = _permission_label(session.get('permission'))
    for turn in turns:
        prompts = {}
        for entry in turn['entries']:
            if entry['event_type'] == 'user_prompt':
                entry['permission_mode'] = permission
                prompts.setdefault(entry['message_id'], entry)
        for entry in turn['entries']:
            if entry['event_type'] == 'file_attachment':
                uploads = [parse_upload(parts[entry['part_id']]['data'], store)]
                entry['attachments'] = uploads
                if entry['message_id'] in prompts:
                    prompts[entry['message_id']].setdefault('file_links', []).extend(uploads)
                entry.pop('evidence', None)  # Raw SQLite evidence remains in entry['raw'].
            elif execution := entry.get('execution'):
                uploads = list(tool_attachments(execution, store))
                if file := recover_file(execution, store):
                    file.update(call_id=entry['call_id'], part_id=entry['part_id'], ordinal=entry['ordinal'])
                    entry['file_links'] = [file]
                    if file['saved_path']:
                        recovered_files.append(file)
            else:
                continue
            for upload in uploads:
                upload.update(message_id=entry['message_id'], part_id=entry['part_id'],
                              call_id=entry['call_id'], ordinal=entry['ordinal'])
                attachments.append(upload)
                if upload['status'] == 'unavailable':
                    failures.append(upload)
            if uploads:
                entry.setdefault('file_links', []).extend(uploads)
    summary['attachments'] = sum(a['status'] == 'extracted' for a in attachments)
    summary['recovered_files'] = len(recovered_files)
    return {'thread': thread, 'session': {'session_id': session_id}, 'source_path': str(path),
            'attachments': attachments, 'attachment_failures': failures,
            'recovered_files': recovered_files,
            'output_directory': str(store.directory) if store else None,
            'messages': messages, 'turns': turns, 'summary': summary}
