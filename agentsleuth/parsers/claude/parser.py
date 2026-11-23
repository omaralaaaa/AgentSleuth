"""Open a selected Claude transcript and reconstruct its recorded evidence."""

from collections import defaultdict

from .artifacts import Artifacts
from .paths import local_directory, resolve_session, within
from .reconstruction import reconstruct
from .records import records, string_value
from .recovery import snapshot_files


def _read(path, progress):
    references = []
    for index, reference in enumerate(records(path), 1):
        references.append(reference)
        if progress and index % 500 == 0:
            progress(f'Reading Claude Code transcript · {index:,} records')
    return references


def _partition(references):
    """Keep sidechain descendants together using their recorded parent links."""
    by_uuid = {uid: ref for ref in references if (uid := string_value((ref['raw'] or {}).get('uuid')))}
    branches = defaultdict(list)
    assigned = {}
    for reference in references:
        chain, visited = [], set()
        current = reference
        while current is not None and id(current) not in assigned and id(current) not in visited:
            visited.add(id(current))
            chain.append(current)
            raw = current['raw'] or {}
            current = by_uuid.get(string_value(raw.get('parentUuid')))
        branch = assigned.get(id(current))
        for ref in reversed(chain):
            raw = ref['raw'] or {}
            if raw.get('isSidechain') is False:
                branch = None
            elif agent := string_value(raw.get('agentId')):
                branch = agent
            elif branch is None and raw.get('isSidechain') is True:
                branch = f'line {ref["line_number"]}'
            assigned[id(ref)] = branch
        branches[assigned[id(reference)]].append(reference)
    return branches


def _subagent_paths(transcript, session_id):
    directory = transcript.parent / session_id / 'subagents'
    if not local_directory(directory):
        return []
    return [path for candidate in sorted(directory.glob('agent-*.jsonl'))
            if (path := within(candidate, directory)) is not None]


def _snapshots(session_id, references, artifacts, operations):
    # Snapshot message IDs identify checkpoints, and each checkpoint can list
    # files tracked across the session. These are separate from prompt media.
    snapshots = []
    for ref in references:
        raw = ref['raw'] or {}
        if raw.get('type') != 'file-history-snapshot':
            continue
        backups = list(snapshot_files(ref, session_id, artifacts))
        snapshots.append({'source': ref, 'files': backups})
        operations.extend(backups)
    return snapshots


def reconstruct_from_thread(history, thread, output_root, progress=None):
    session_id = thread['id']
    evidence_root = history.expanduser().resolve().parent
    projects = thread.get('projects') or ([thread['cwd']] if thread.get('cwd') else [])
    if progress:
        progress('Resolving Claude Code session transcript…')
    transcript = resolve_session(evidence_root / 'projects', session_id, projects)
    references = _read(transcript, progress)
    partitioned = _partition(references)
    primary = partitioned.pop(None, [])
    for ref in primary:
        recorded_id = (ref['raw'] or {}).get('sessionId')
        if string_value(recorded_id) and recorded_id != session_id:
            raise ValueError(f'Claude Code transcript session ID mismatch at line {ref["line_number"]}: {transcript}')

    subagents = [(path, _read(path, progress)) for path in _subagent_paths(transcript, session_id)]
    all_records = references + [ref for _, group in subagents for ref in group]
    directories = [*(projects or []), *(cwd for ref in all_records
                                        if (cwd := string_value((ref['raw'] or {}).get('cwd'))))]
    artifacts = Artifacts(output_root, evidence_root, session_id, directories,
                          title=thread.get('export_title', thread.get('name')))
    turns, attachments, operations = reconstruct(session_id, primary, artifacts, progress)
    entries = [entry for turn in turns for entry in turn['entries']]
    snapshots = _snapshots(session_id, primary, artifacts, operations)
    sidechains = []
    branches = [(label, transcript, group) for label, group in partitioned.items()]
    for path, group in subagents:
        branches.extend((label or path.stem, path, refs) for label, refs in _partition(group).items())
    for branch, path, group in branches:
        branch_turns, branch_attachments, branch_operations = reconstruct(session_id, group, artifacts, progress)
        branch_snapshots = _snapshots(session_id, group, artifacts, branch_operations)
        sidechains.append({'branch': branch, 'source_path': str(path), 'records': group,
                           'turns': branch_turns, 'snapshots': branch_snapshots})
        attachments.extend(branch_attachments)
        operations.extend(branch_operations)

    recovered = [file for file in operations if file['saved_path']]
    summary = {'turns': len(turns), 'activities': sum(entry['kind'] == 'activity' for entry in entries),
               'messages': sum(entry['kind'] == 'message' for entry in entries),
               'attachments': sum(item['status'] == 'extracted' for item in attachments),
               'recovered_files': len(recovered), 'max_ordinal': len(entries),
               'invalid_json': sum(ref['raw'] is None for ref in all_records)}
    return {'thread': thread, 'session': {'session_id': session_id}, 'source_path': str(transcript),
            'source_detail': f'Transcript: {transcript}', 'output_directory': str(artifacts.directory),
            'records': references, 'turns': turns, 'sidechains': sidechains, 'snapshots': snapshots,
            'attachments': attachments, 'file_operations': operations, 'recovered_files': recovered,
            'summary': summary}
