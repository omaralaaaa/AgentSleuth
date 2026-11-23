"""Group Claude history records into a conversation discovery index."""

import math
import re

from .paths import SESSION_ID, resolve_session, transcript_index
from .records import records, string_value, timestamp_label
from ...core.utils import short


SLASH_COMMAND = re.compile(r'\s*/[\w:-]+(?:[ \t][^\r\n]*)?\s*\Z')


def _time(reference):
    value = reference['raw'].get('timestamp')
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return value if isinstance(value, float) and math.isfinite(value) else None


def load_threads(path):
    path = path.expanduser().resolve()
    groups = {}
    for reference in records(path):
        raw = reference['raw'] or {}
        session_id = string_value(raw.get('sessionId'))
        if SESSION_ID.fullmatch(session_id):
            groups.setdefault(session_id, []).append(reference)
    projects = path.parent / 'projects'
    index = transcript_index(projects, groups)
    sessions = []
    for session_id, history in groups.items():
        ordered = sorted(history, key=lambda row: (_time(row) is None, _time(row) or 0, row['line_number']))
        recent = sorted(history, key=lambda row: (_time(row) is None, -(_time(row) or 0), -row['line_number']))
        projects_seen = list(dict.fromkeys(
            record['raw']['project'] for record in recent
            if string_value(record['raw'].get('project')).strip()
        ))
        title = next((display for record in ordered
                      if (display := string_value(record['raw'].get('display')).strip())
                      and not SLASH_COMMAND.fullmatch(display)), '')
        recorded_times = [timestamp for row in ordered if (timestamp := _time(row)) is not None]
        try:
            transcript = resolve_session(projects, session_id, projects_seen, index)
            source, state = f'Transcript: {transcript}', 'Available'
        except FileNotFoundError as error:
            transcript, source, state = None, str(error), 'Missing'
        except ValueError as error:
            transcript, source, state = None, str(error), 'Ambiguous'
        created = recorded_times[0] if recorded_times else None
        updated = recorded_times[-1] if recorded_times else None
        cwd = projects_seen[0] if projects_seen else ''
        sessions.append({'id': session_id, 'name': short(title, 100) or 'Untitled Claude Session',
                         'cwd': cwd, 'projects': projects_seen, 'history': history,
                         'time_created': created, 'created_label': timestamp_label(created),
                         'time_updated': updated, 'updated_label': timestamp_label(updated),
                         'transcript_path': str(transcript) if transcript else None,
                         'source_detail': source, 'history_status': f'{state} · {len(history)} entries'})
    return sorted(sessions, key=lambda row: (row['time_updated'] is None, -(row['time_updated'] or 0), row['id']))
