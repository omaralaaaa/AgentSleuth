"""Normalize Claude transcript records in original line and content-block order."""

import hashlib
import json
import re

from .attachments import MEDIA_TYPES, attachment
from .correlation import correlate
from .history import SLASH_COMMAND
from .records import object_value, string_value, timestamp_label
from .recovery import operation
from ...core.utils import short


INTERNAL_TEXT = re.compile(
    r'<(local-command-(?:caveat|stdout|stderr)|command-(?:name|message|args)|'
    r'system-reminder|task-notification|bash-(?:input|stdout|stderr))\b[^>]*>.*?</\1\s*>',
    re.IGNORECASE | re.DOTALL,
)
ERROR_PREFIX = re.compile(r'^(?:(?:API\s*Error|HTTP(?:\s+Error)?)\s*:?\s*)?'
                          r'(?:[45]\d{2}\b\s*[-:]?\s*)?', re.IGNORECASE)


def _user_text(text):
    if SLASH_COMMAND.fullmatch(text) or text.lstrip().startswith(('<command-name>', '<command-message>')):
        return ''
    return INTERNAL_TEXT.sub('', text).strip() if '<' in text else text


def _error_text(*values):
    """Extract a display message from plain errors and JSON API envelopes."""
    candidates = list(reversed(values))
    while candidates:
        value = candidates.pop()
        if isinstance(value, str):
            text = value.strip()
            if not text:
                continue
            payload = text[ERROR_PREFIX.match(text).end():]
            if not payload.startswith(('{', '[')):
                return text
            try:
                value, _ = json.JSONDecoder().raw_decode(payload)
            except (ValueError, RecursionError):
                if payload.startswith('[') and payload == text and not re.match(r'\[\s*[{"\[]', payload):
                    return text  # A bracketed plain-text label such as [Timeout].
                continue
        if isinstance(value, dict):
            inner = value.get('error')
            fields = (inner if isinstance(inner, dict) else None,
                      object_value(value.get('data')).get('message'),
                      value.get('message'), value.get('detail'), value.get('errors'),
                      string_value(inner), value.get('name'))
            candidates.extend(reversed(fields))
        elif isinstance(value, list):
            candidates.extend(reversed(value))
    return 'No error message recorded.'


def _source_entry(session_id, source, block_index):
    record = source['raw']
    message = object_value(record.get('message'))
    timestamp = record.get('timestamp')
    return {'agent': 'claude', 'session_id': session_id, 'message_id': message.get('id'),
            'uuid': record.get('uuid'), 'parent_uuid': record.get('parentUuid'),
            'request_id': record.get('requestId'), 'role': record.get('type'),
            'timestamp': timestamp, 'timestamp_label': timestamp_label(timestamp),
            'line_number': source['line_number'], 'block_index': block_index, 'raw': {'source': source}}


def _message(session_id, source, index, text, files=(), error=False):
    entry = _source_entry(session_id, source, index)
    event_type = 'user_prompt' if entry['role'] == 'user' else 'assistant_response'
    entry.update(kind='message', event_type='assistant_error' if error else event_type,
                 text=text, file_links=list(files))
    return entry


def _execution(session_id, source, index, block=None):
    entry = _source_entry(session_id, source, index)
    block = block or {}
    tool = string_value(block.get('name')) or None
    start = entry['timestamp'] if block else None
    args = block.get('input')
    entry.update(kind='activity', activity_type='ToolExecution', event_type='execution',
                 call_id=string_value(block.get('id')) or None,
                 execution={'tool': tool, 'arguments': args, 'command': object_value(args).get('command'),
                            'partial_input': None, 'status': 'Result missing', 'output': None,
                            'error': None, 'metadata': None, 'start': start, 'end': None,
                            'start_label': timestamp_label(start), 'end_label': ''},
                 file_links=[])
    entry['raw'].update(calls=[source] if block else [], results=[], tool_use=block or None)
    return entry


def _tool_result(source, index, block, metadata):
    return {'call_id': string_value(block.get('tool_use_id')) or None, 'source': source,
            'block_index': index, 'block': block, 'metadata': metadata}


def _content(blocks, source, artifacts, attachments):
    """Collect text and media links, keeping raw blocks in the source record."""
    text, links = [], []
    for index, item in enumerate(blocks):
        block = object_value(item)
        kind = string_value(block.get('type'))
        if kind in MEDIA_TYPES:
            link = attachment(block, source, index, artifacts)
            links.append(link)
            attachments.append(link)
        elif isinstance(item, str) or kind == 'text':
            text.append(item if isinstance(item, str) else string_value(block.get('text')))
    return '\n'.join(text), links


def _result_content(result, artifacts, attachments):
    value = result['block'].get('content')
    links = []
    if isinstance(value, list):
        text, links = _content(value, result['source'], artifacts, attachments)
        other = [part for part in value if not isinstance(part, str)
                 and string_value(object_value(part).get('type')) not in MEDIA_TYPES | {'text'}]
        value = [text, *other] if text and other else text if text else other or None
    if value is None:
        metadata = result['metadata']
        value = {key: metadata[key] for key in ('stdout', 'stderr') if key in metadata} or None
    return value, links


def _unique(values):
    distinct = []
    for value in values:
        if value is not None and value not in distinct:
            distinct.append(value)
    return distinct[0] if len(distinct) == 1 else distinct or None


def _finish_execution(entry, artifacts, attachments):
    execution = entry['execution']
    results = entry['raw']['results']
    outputs, errors, statuses, metadata = [], [], set(), {}
    for result in results:
        value, links = _result_content(result, artifacts, attachments)
        entry['file_links'].extend(links)
        block = result['block']
        meta = result['metadata']
        metadata.update(meta)
        is_error = block.get('is_error')
        recorded_error = block.get('error')
        if is_error is True or recorded_error is not None:
            statuses.add('failed')
            errors.append(recorded_error if recorded_error is not None else value)
            if recorded_error is not None and value != recorded_error:
                outputs.append(value)
        else:
            if meta.get('interrupted') is True:
                statuses.add('interrupted')
            elif is_error is False or (is_error is None and ('content' in block or value is not None)):
                statuses.add('completed')
            else:
                statuses.add('Result recorded')
            outputs.append(value)
    if results:
        end = results[-1]['source']['raw'].get('timestamp')
        status = next(iter(statuses)) if len(statuses) == 1 else 'Conflicting results'
        execution.update(status=status, output=_unique(outputs), error=_unique(errors),
                         end=end, end_label=timestamp_label(end))
    details = {key: metadata[key] for key in ('structuredPatch', 'originalFile', 'modifiedFile')
               if key in metadata and metadata[key] is not None}
    execution['metadata'] = details or None
    return operation(execution, metadata, artifacts)


def reconstruct(session_id, references, artifacts, progress=None):
    entries, calls, results, attachments, file_operations = [], [], [], [], []
    seen_records, seen_calls = set(), {}
    for count, source in enumerate(references, 1):
        if progress and count % 250 == 0:
            progress(f'Reconstructing Claude Code · {count:,} records')
        record = source['raw'] or {}
        role = record.get('type')
        if role not in ('user', 'assistant', 'attachment'):
            continue
        if role == 'attachment':
            block = object_value(record.get('attachment'))
            if string_value(block.get('type')) in MEDIA_TYPES:
                _, links = _content([block], source, artifacts, attachments)
                entry = _source_entry(session_id, source, 0)
                entry.update(kind='activity', activity_type='file_attachment',
                             event_type='file_attachment', file_links=links, part_type=None, text='')
                entries.append(entry)
            continue
        message = object_value(record.get('message'))
        content = message.get('content')
        blocks = content if isinstance(content, list) else [content]
        tagged = [(index, block) for index, block in enumerate(blocks) if isinstance(block, dict)]
        returned = [(index, block) for index, block in tagged if block.get('type') == 'tool_result']
        if returned:
            meta = object_value(record.get('toolUseResult'))
            for index, block in returned:
                keyed = object_value(meta.get(string_value(block.get('tool_use_id'))))
                results.append(_tool_result(source, index, block, keyed or (meta if len(returned) == 1 else {})))
            if role == 'user':
                continue
        if record.get('isMeta') or message.get('role') not in (None, role):
            continue
        if role == 'user':
            joined, links = _content(blocks, source, artifacts, attachments)
            text = _user_text(joined)
            if text.strip() or links:
                entries.append(_message(session_id, source, 0, text, links))
            continue
        # One model message can have several distinct JSONL records.
        errors = (message.get('error'), record.get('error'))
        is_error = record.get('isApiErrorMessage') is True or any(error is not None for error in errors)
        display_types = MEDIA_TYPES | {'text', 'tool_use'}
        if not is_error and not any(isinstance(item, str) or
                                    string_value(object_value(item).get('type')) in display_types
                                    for item in blocks):
            continue
        identity = string_value(message.get('id')) or string_value(record.get('uuid'))
        if identity:
            fingerprint = (content, errors) if is_error else content
            digest = hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode()).digest()
            key = identity, is_error, digest
            repeated = key in seen_records
            seen_records.add(key)
        else:
            repeated = False
        if is_error and not repeated:
            text, links = _content(blocks, source, artifacts, attachments)
            entries.append(_message(session_id, source, 0, _error_text(text, *errors), links, error=True))
        for index, item in enumerate(blocks):
            block = object_value(item)
            kind = string_value(block.get('type'))
            if kind == 'tool_use':
                call = _execution(session_id, source, index, block)
                call_id = call['call_id']
                key = call_id, identity, json.dumps(block, sort_keys=True)
                if call_id and identity and key in seen_calls:
                    seen_calls[key]['raw']['calls'].append(source)
                    continue
                if call_id and identity:
                    seen_calls[key] = call
                entries.append(call)
                calls.append(call)
            elif not repeated and not is_error and (isinstance(item, str) or kind == 'text' or kind in MEDIA_TYPES):
                text, links = _content([item], source, artifacts, attachments)
                if text or links:
                    entries.append(_message(session_id, source, index, text, links))

    for result in correlate(calls, results, references):
        entry = _execution(session_id, result['source'], result['block_index'])
        entry['call_id'] = result['call_id']
        entry['raw']['results'].append(result)
        entries.append(entry)
        calls.append(entry)
    for index, entry in enumerate(calls, 1):
        if progress and index % 100 == 0:
            progress(f'Processing Claude Code tool evidence · {index:,} executions')
        if file := _finish_execution(entry, artifacts, attachments):
            file['source'] = entry['raw']
            entry['file_links'].append(file)
            file_operations.append(file)

    turns = []
    entries.sort(key=lambda entry: (entry['line_number'], entry['block_index']))
    for ordinal, entry in enumerate(entries, 1):
        entry['ordinal'] = ordinal
        if not turns or entry['event_type'] == 'user_prompt':
            title = (entry['text'] or 'Attached evidence') if entry['event_type'] == 'user_prompt' else 'Agent activity'
            turns.append({'turn_id': entry['uuid'] or entry['line_number'], 'title': short(title, 85),
                          'first_ordinal': ordinal, 'entries': []})
        turns[-1]['entries'].append(entry)
    return turns, attachments, file_operations
