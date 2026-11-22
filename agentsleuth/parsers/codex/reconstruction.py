"""Orchestrate rollout parsing, correlation, attachment extraction and recovery."""

import json
from pathlib import Path

from .attachments import AttachmentExtractor
from .events import (
    classify, normalize_message, normalize_call, normalize_output,
    normalize_activity, deduplicate_messages, correlate,
)
from .paths import rollout_for_thread, _result_dir
from .recovery import _recover_file_changes
from ...core.utils import short


def reconstruct_from_thread(db_path: Path, thread: dict, root: Path, progress=None):
    """Parse selected rollout in ordinal order; save extracted assets only, no reports."""
    source = rollout_for_thread(db_path, thread)
    destination = _result_dir(root.expanduser().resolve(), thread)
    extractor = AttachmentExtractor(destination / 'attachments')
    messages, calls, outputs, activities = [], [], [], []
    valid, invalid, max_ordinal = 0, 0, -1
    session = {}
    with source.open('r', encoding='utf-8-sig', errors='replace') as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    invalid += 1
                    continue
            except json.JSONDecodeError:
                invalid += 1
                continue
            if record.get('type') == 'session_meta':
                p = record.get('payload') or {}
                session = {
                    'session_id': p.get('id') or p.get('session_id'),
                    'cwd': p.get('cwd'),
                    'cli_version': p.get('cli_version'),
                }
            ordinal = record.get('ordinal')
            if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 0:
                continue
            max_ordinal = max(max_ordinal, ordinal)
            valid += 1
            classification = classify(record)
            if not classification:
                continue
            record = extractor.sanitize(record, record)
            if (m := normalize_message(record)):
                messages.append(m)
            if (c := normalize_call(record)):
                calls.append(c)
            if (o := normalize_output(record)):
                outputs.append(o)
            if (a := normalize_activity(record)):
                activities.append(a)
            if progress and line_no % 250 == 0:
                progress(f'Parsing rollout: {line_no:,} lines…')
    messages = deduplicate_messages(messages)
    # Keep this correlation pass even though calls/outputs are not rendered.
    # call_id + output ordinal delimit candidate executions; command matching
    # then associates each activity with its likely parent tool call.
    correlate(calls, outputs, activities)
    # Tool calls and outputs remain in the forensic pipeline above: they are
    # required to correlate CommandExecution/FileChange activities reliably.
    # They are intentionally omitted from the conversation UI because the
    # execution/activity records already contain the useful command/result
    # details and rendering both creates duplicate, expensive blocks.
    entries = messages + activities
    entries.sort(key=lambda x: x['ordinal'])
    by_turn = {}
    for e in entries:
        by_turn.setdefault(e.get('turn_id') or 'unknown-turn', []).append(e)
    turns = []
    for tid, es in by_turn.items():
        prompt = next((e['text'] for e in es if e['kind'] == 'message' and e['role'] == 'user'), '')
        turns.append({'turn_id': tid, 'title': short(prompt or 'Agent activity', 85),
                      'entries': es, 'first_ordinal': es[0]['ordinal']})
    turns.sort(key=lambda t: t['first_ordinal'])
    recovered = _recover_file_changes(activities, destination)
    summary = {
        'total_records': valid, 'invalid_json': invalid, 'max_ordinal': max_ordinal,
        'turns': len(turns), 'messages': len(messages), 'tool_calls': len(calls),
        'activities': len(activities), 'attachments': len(extractor.entries),
        'recovered_files': len(recovered),
    }
    return {'thread': thread, 'source_path': str(source), 'output_directory': str(destination),
            'session': session, 'turns': turns, 'summary': summary,
            'attachments': extractor.entries, 'recovered_files': recovered,
            'attachment_failures': extractor.failures}
