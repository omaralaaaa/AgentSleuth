"""Reconstruct ordered OpenCode timeline events from SQLite records."""

import json
from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite

from ...core.utils import short
from .database import ORDER_FIELDS, SKIPPED_PART_TYPES


ARTIFACT_TYPES = {'file': 'file_attachment', 'patch': 'file_change'}
TOOL_FIELDS = {'input': 'arguments', 'output': 'output', 'error': 'error',
               'metadata': 'metadata', 'raw': 'partial_input'}


def _object(value):
    return value if isinstance(value, dict) else {}


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            pass
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def _timestamp_key(value):
    if (number := _number(value)) is not None:
        return number  # OpenCode's SQLite and JSON times are Unix milliseconds.
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).timestamp() * 1000
        except (ValueError, OverflowError, OSError):
            pass
    return float('inf')


def _timestamp_label(value):
    if (number := _number(value)) is not None:
        try:
            return datetime.fromtimestamp(number / 1000, tz=timezone.utc).isoformat(
                sep=' ', timespec='milliseconds'
            ).replace('+00:00', ' UTC')
        except (ValueError, OverflowError, OSError):
            pass
    return str(value) if value is not None else ''


def _decode_record(row):
    fields = {key.lower(): value for key, value in row.items()}
    raw_data = fields.get('data')
    try:
        data = json.loads(raw_data) if raw_data is not None else None
    except (ValueError, TypeError, RecursionError):
        data = None
    return fields, data


def _sequence(fields, values):
    json_fields = {key.lower(): value for key, value in values.items()}
    return next((number for source in (fields, json_fields) for key in ORDER_FIELDS
                 if (number := _number(source.get(key))) is not None), None)


def _position(fields, values, sequence, *, part):
    times = _object(values.get('time'))
    state_times = _object(_object(values.get('state')).get('time')) if part else {}
    created = fields.get('time_created')
    updated = fields.get('time_updated')
    candidates = (created, times.get('created'), times.get('start'), state_times.get('start'),
                  times.get('completed'), times.get('end'), state_times.get('end'), updated)
    timestamp = next((value for value in candidates if _timestamp_key(value) != float('inf')), None)
    return {'id': fields['id'], 'timestamp': timestamp, 'sequence': sequence}


def _record(row, fields, data, *, part=False):
    values = _object(data)
    record = _position(fields, values, _sequence(fields, values), part=part)
    record.update(session_id=fields.get('session_id'), data=data, raw=row,
                  time_created=fields.get('time_created'), time_updated=fields.get('time_updated'))
    if part:
        record['message_id'] = fields['message_id']
        record['type'] = values.get('type') if isinstance(values.get('type'), str) else None
    else:
        record['role'] = values.get('role') if isinstance(values.get('role'), str) else None
    return record


def _ordered(records):
    chronological = sorted(records, key=lambda record: (
        _timestamp_key(record['timestamp']), str(record['id'])
    ))
    sequenced = sorted((record for record in chronological if record['sequence'] is not None),
                       key=lambda record: record['sequence'])
    explicit = iter(sequenced)
    # Keep unnumbered records in their chronological slots and honor recorded
    # sequences among the remaining records. Timestamp and ID break sequence ties.
    return [next(explicit) if record['sequence'] is not None else record for record in chronological]


def _execution(data, part):
    state = _object(data.get('state'))
    times = _object(state.get('time'))
    execution = {target: state[key] for key, target in TOOL_FIELDS.items() if key in state}
    execution['raw'] = part['raw']
    if 'tool' in data:
        execution['tool'] = data['tool']
    if 'status' in state:
        execution['recorded_status'] = state['status']
        execution['status'] = 'failed' if state['status'] == 'error' else state['status']
    execution.update({key: times[key] for key in ('start', 'end') if key in times})
    return execution


def _event(session_id, message, part=None, *, error_text=None):
    source = part if part is not None else message
    data = _object(source['data'])
    part_type = part['type'] if part is not None else None
    role = message['role']
    call_id = data.get('callID') if part is not None else None
    entry = {
        'agent': 'opencode', 'session_id': session_id, 'message_id': message['id'],
        'part_id': part['id'] if part is not None else None, 'call_id': call_id,
        'role': role, 'part_type': part_type, 'timestamp': source['timestamp'],
        'timestamp_label': _timestamp_label(source['timestamp']),
        'raw': {'message': message['raw'], 'parts': [part['raw']] if part is not None else []},
    }
    if error_text is not None:
        entry.update(kind='message', event_type='assistant_error', text=error_text)
    elif part_type == 'text' and role in ('user', 'assistant') and isinstance(data.get('text'), str):
        event_type = 'user_prompt' if role == 'user' else 'assistant_response'
        entry.update(kind='message', event_type=event_type, text=data['text'])
    elif part_type == 'tool':
        execution = _execution(data, part)
        entry.update(kind='activity', activity_type='ToolExecution', event_type='execution',
                     execution=execution)
    else:
        event_type = ARTIFACT_TYPES.get(part_type, 'raw_part' if part is not None else 'raw_message')
        raw_data = next((value for key, value in source['raw'].items() if key.lower() == 'data'), None)
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode('utf-8', errors='backslashreplace')
        evidence = raw_data if raw_data is not None else json.dumps(source['raw'], default=repr)
        entry.update(kind='activity', activity_type=event_type, event_type=event_type, evidence=evidence)
    return entry


def _message_events(session_id, message):
    entries = []
    tools = {}
    for part in message['parts']:
        entry = _event(session_id, message, part)
        call_id = entry['call_id']
        if entry['event_type'] == 'execution' and isinstance(call_id, str) and call_id:
            previous = tools.get(call_id)
            if previous is not None:
                # Duplicate snapshots occupy the first recorded position. Later
                # fields update the display, and every original row stays attached.
                previous['raw']['parts'].append(part['raw'])
                previous['execution'].update(entry['execution'])
                continue
            tools[call_id] = entry
        entries.append(entry)
    error = _object(message['data']).get('error')
    if message['role'] == 'assistant' and error is not None:
        error = _object(error)
        candidates = (_object(error.get('data')).get('message'), error.get('message'), error.get('name'))
        error_text = next((value for value in candidates if isinstance(value, str) and value.strip()),
                          'No error message recorded.')
        entries.append(_event(session_id, message, error_text=error_text))
    return entries


def reconstruct(session_id, message_rows, part_rows, progress=None, *, messages_with_parts):
    """Keep message and part identity separate from display turns and ordinals."""
    parts_by_message = defaultdict(list)
    part_count = 0
    for number, row in enumerate(part_rows, 1):
        if progress and number % 500 == 0:
            progress(f'Reading OpenCode timeline · {number:,} parts')
        fields, data = _decode_record(row)
        values = _object(data)
        part_type = values.get('type')
        if isinstance(part_type, str) and part_type in SKIPPED_PART_TYPES:
            if (sequence := _sequence(fields, values)) is not None:
                # Preserve the ordering slot without retaining the Part or its contents.
                parts_by_message[fields['message_id']].append(
                    _position(fields, values, sequence, part=True)
                )
            continue
        parts_by_message[fields['message_id']].append(_record(row, fields, data, part=True))
        part_count += 1

    messages = _ordered(_record(row, *_decode_record(row)) for row in message_rows)
    turns = []
    ordinal = activities = tools = 0
    for message in messages:
        message['parts'] = [part for part in _ordered(parts_by_message[message['id']]) if 'raw' in part]
        entries = _message_events(session_id, message)
        if not entries:
            if message['id'] in messages_with_parts:
                continue
            entries = [_event(session_id, message)]
        if not turns or message['role'] == 'user':
            prompt = next((entry['text'] for entry in entries if entry['event_type'] == 'user_prompt'), '')
            turns.append({'turn_id': message['id'], 'entries': [], 'first_ordinal': ordinal + 1,
                          'title': short(prompt or 'Agent activity', 85)})
        for entry in entries:
            ordinal += 1
            entry['ordinal'] = ordinal
            activities += entry['kind'] == 'activity'
            tools += entry['event_type'] == 'execution'
            if execution := entry.get('execution'):
                for key in ('tool', 'status', 'recorded_status', 'start', 'end', *TOOL_FIELDS.values()):
                    execution.setdefault(key, None)
                execution['command'] = _object(execution['arguments']).get('command')
                execution['start_label'] = _timestamp_label(execution['start'])
                execution['end_label'] = _timestamp_label(execution['end'])
        turns[-1]['entries'].extend(entries)

    summary = {'turns': len(turns), 'messages': len(messages), 'parts': part_count,
               'activities': activities, 'tool_calls': tools, 'max_ordinal': ordinal,
               'attachments': 0, 'recovered_files': 0}
    return messages, turns, summary
