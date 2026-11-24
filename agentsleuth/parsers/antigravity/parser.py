"""Read Antigravity's generated JSONL and SQLite evidence without invoking the agent."""

import json
import re
import sqlite3
from collections import defaultdict
from contextlib import closing
from pathlib import Path

from ...core.export import session_directory
from ...core.artifacts import ArtifactStore
from ...core.utils import safe_text, short
from .attachments import recover_uploads


TRANSCRIPT = Path('.system_generated/logs/transcript.jsonl')
TOOL_DISPLAY_METADATA = {'toolSummary', 'toolAction', 'WaitMsBeforeAsync'}
PROMPT_TAG = re.compile(r'<(/?)(USER_REQUEST|ADDITIONAL_METADATA|USER_SETTINGS_CHANGE)'
                        r'[ \t]*(?:>|(?=\r?$))', re.MULTILINE)


def _user_prompt(step):
    content = step.get('content')
    for source in (step, content if isinstance(content, dict) else {}):
        for key in ('user_request', 'userRequest', 'USER_REQUEST'):
            if isinstance(value := source.get(key), str):
                return value if value.strip() else ''
    if not isinstance(content, str):
        return ''

    tags = list(PROMPT_TAG.finditer(content))
    openings = defaultdict(list)
    ends = {}
    for index, tag in enumerate(tags):
        closing, name = tag.groups()
        if not closing:
            openings[name].append(index)
        elif openings[name]:
            ends[openings[name].pop()] = index

    requests, outside = [], []
    index = cursor = 0
    while index < len(tags):
        tag = tags[index]
        closing, name = tag.groups()
        outside.append(content[cursor:tag.start()])
        cursor = tag.end()
        end = ends.get(index)
        index += 1
        if closing:
            continue
        # A complete wrapper can contain literal tags written by the user.
        # An incomplete wrapper ends at the next known marker or at EOF.
        boundary = end if end is not None else index
        stop = tags[boundary].start() if boundary < len(tags) else len(content)
        if name == 'USER_REQUEST':
            requests.append(re.sub(r'^\r?\n|\r?\n\Z', '', content[cursor:stop]))
        if end is not None:
            cursor, index = tags[end].end(), end + 1
        else:
            cursor = stop

    if requests:
        return '\n\n'.join(dict.fromkeys(text for text in requests if text.strip()))
    outside.append(content[cursor:])
    text = ''.join(outside)
    return text if text.strip() else ''


def _connect(path):
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    return db


def _related(root, session_id, source):
    if re.fullmatch(r'[A-Za-z0-9_-]{1,160}', session_id):
        for path in (root / 'brain' / session_id / TRANSCRIPT,
                     root / 'conversations' / (session_id + '.db')):
            if path.resolve().is_relative_to(root) and path.is_file():
                return path.resolve()
    return source


def load_threads(path):
    path = Path(path).resolve()
    if path.is_dir():
        threads = []
        ids = set()
        for name in ('brain', 'conversations'):
            parent = path / name
            if not parent.is_dir() or parent.resolve() != parent:
                continue
            for child in parent.iterdir():
                sid = child.name if name == 'brain' else child.stem
                if name == 'conversations' and child.suffix.lower() != '.db':
                    continue
                if sid in ids:
                    continue
                source = _related(path, sid, path)
                if source != path:
                    ids.add(sid)
                    threads.append(dict(id=sid, name=sid, export_title='', cwd='', source_detail=str(source)))
        if not threads:
            raise ValueError('No generated transcripts or supported trajectory databases in this folder.')
        return sorted(threads, key=lambda t: t['id'])
    if path.suffix.lower() == '.jsonl':
        sid = path.parents[2].name if path.as_posix().endswith('/' + TRANSCRIPT.as_posix()) else path.stem
        return [dict(id=sid, name=sid, export_title='', cwd='', source_detail=str(path))]
    with closing(_connect(path)) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'conversation_summaries' in tables:
            threads = []
            for row in db.execute('SELECT conversation_id,title,workspace_uris,last_modified_time '
                                  'FROM conversation_summaries ORDER BY last_modified_time DESC, conversation_id'):
                sid = row['conversation_id']
                if not isinstance(sid, str):
                    continue
                try:
                    roots = json.loads(row['workspace_uris'])
                except (TypeError, ValueError):
                    roots = None
                cwd = ', '.join(x for x in roots if isinstance(x, str)) if isinstance(roots, list) else ''
                threads.append(dict(id=sid, name=row['title'] or sid, export_title=row['title'], cwd=cwd,
                                    source_detail=f'Antigravity session {sid}', indexed=True))
            return threads
        if 'steps' in tables:
            return [dict(id=path.stem, name=path.stem, export_title='', cwd='', source_detail=str(path))]
    raise ValueError('Expected an Antigravity summary index or trajectory database.')


def _records(path):
    if path.suffix.lower() == '.jsonl':
        with path.open(encoding='utf-8-sig') as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    step = json.loads(line)
                    if not isinstance(step, dict) or not isinstance(step.get('type'), str):
                        raise ValueError('Missing step type')
                except ValueError:
                    step = {'type': 'UNREADABLE_RECORD', 'content': f'Malformed record at line {line_no}'}
                yield step
    else:
        with closing(_connect(path)) as db:
            for row in db.execute('SELECT idx,step_type,status FROM steps ORDER BY idx'):
                yield dict(step_index=row['idx'], type='Trajectory step', status=row['status'],
                           content=f"Recorded step type {row['step_type']} · status {row['status']}")


_USER_REQUEST = re.compile(
    r'\A\s*\\?<USER_REQUEST>\\?(?:\r?\n)?(?P<request>.*?)'
    r'(?:\\?\r?\n)?\\?</USER_REQUEST>(?=\\?\s*(?:\Z|\\?<(?:ADDITIONAL_METADATA|USER_SETTINGS_CHANGE)>))',
    re.DOTALL,
)


def reconstruct_from_thread(path, thread, output_root=None, progress=None):
    path = Path(path).resolve()
    source = path
    if path.is_dir():
        source = _related(path, thread['id'], path)
        if source == path:
            raise FileNotFoundError('Session evidence is missing from the selected folder.')
    elif thread.get('indexed'):
        source = _related(path.parent, thread['id'], path)
    elif path.parent.name == 'conversations' and path.suffix.lower() == '.db':
        source = _related(path.parent.parent, thread['id'], path)
    turns, user_records = [], []
    attachments = []
    session = source.parents[2] if source.as_posix().endswith('/' + TRANSCRIPT.as_posix()) else None
    store = None
    if output_root is not None:
        title = thread.get('export_title', thread.get('name'))
        destination = session_directory(output_root, 'Antigravity', thread['id'], title)
        store = ArtifactStore(destination, [session.parent.parent if session else source.parent])
    ordinal = activities = tool_calls = messages = 0
    indexed_only = thread.get('indexed') and source == path
    records = () if indexed_only else _records(source)
    for n, step in enumerate(records, 1):
        if progress and n % 200 == 0:
            progress(f'Reading Antigravity evidence · {n:,} steps')
        kind = step['type']
        if kind == 'USER_INPUT':
            user_records.append(step)
            content = _user_prompt(step)
            uploads = recover_uploads(step, session / '.user_uploaded' if session else None, store)
            attachments.extend(uploads)
        else:
            content = safe_text(step.get('content'))
        base = dict(agent='antigravity', timestamp_label=safe_text(step.get('created_at')),
                    timestamp=safe_text(step.get('created_at')), step_index=step.get('step_index'),
                    status=step.get('status'), truncated_fields=step.get('truncated_fields'))
        entries = []
        if (kind == 'USER_INPUT' and (content or uploads)) or (kind == 'PLANNER_RESPONSE' and content):
            entry = dict(base, kind='message', role='user' if kind == 'USER_INPUT' else 'assistant',
                         text=content)
            if kind == 'USER_INPUT':
                entry['raw'] = step
                entry['file_links'] = uploads
            entries.append(entry)
            messages += 1
        for call in step.get('tool_calls') or []:
            if isinstance(call, dict):
                arguments = call.get('args')
                if isinstance(arguments, dict):
                    arguments = {key: value for key, value in arguments.items()
                                 if key not in TOOL_DISPLAY_METADATA}
                entries.append(dict(base, kind='activity', activity_type='ToolExecution',
                                    part_type='Tool request', tool_name=call.get('name'),
                                    tool_arguments=arguments, raw=call))
                tool_calls += 1
        if not entries and kind != 'USER_INPUT':
            # Preserve unfamiliar step kinds and recorded errors; never infer a
            # tool result from proximity to a planner request.
            evidence = content or safe_text(step.get('thinking')) or kind
            if step.get('error'):
                evidence += '\n' + safe_text(step['error'])
            entries.append(dict(base, kind='activity', activity_type=kind, part_type=kind,
                                evidence=evidence))
        if not turns or kind == 'USER_INPUT':
            turns.append(dict(turn_id=f'{thread["id"]}:{n}', title=short(content, 85) if kind == 'USER_INPUT'
                              else 'Session activity', entries=[], first_ordinal=ordinal + 1))
        for entry in entries:
            ordinal += 1
            entry['ordinal'] = ordinal
            activities += entry['kind'] == 'activity'
            turns[-1]['entries'].append(entry)
    detail = str(source)
    if indexed_only:
        detail = 'Summary only · no generated transcript or readable trajectory database beside this index'
    elif source.suffix.lower() == '.db':
        detail += ' · step metadata only (binary payloads are not decoded)'
    return dict(thread=thread, turns=turns, user_records=user_records,
                attachments=attachments,
                attachment_failures=[a for a in attachments if a['status'] == 'unavailable'],
                output_directory=str(store.directory) if store else None,
                source_path=str(source), source_detail=detail,
                summary=dict(turns=len(turns), activities=activities, messages=messages,
                             tool_calls=tool_calls, max_ordinal=ordinal,
                             attachments=sum(a['status'] == 'extracted' for a in attachments),
                             recovered_files=0))
