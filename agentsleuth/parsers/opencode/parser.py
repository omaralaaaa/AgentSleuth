"""Build a viewer result from a selected OpenCode session."""

from .database import read_conversation
from .reconstruction import reconstruct


def reconstruct_from_thread(path, thread, _output_root=None, progress=None):
    session_id = thread['id']
    message_rows, part_rows, messages_with_parts = read_conversation(path, session_id, progress)
    if progress:
        progress('Reconstructing OpenCode timeline…')
    messages, turns, summary = reconstruct(
        session_id, message_rows, part_rows, progress, messages_with_parts=messages_with_parts
    )
    return {'thread': thread, 'session': {'session_id': session_id}, 'source_path': str(path),
            'messages': messages, 'turns': turns, 'summary': summary}
