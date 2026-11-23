"""Search normalized transcript fields without consulting Tk widgets or evidence files."""

from .utils import safe_text


ALL_ENTRIES = 'All entries'


def filter_values(entry):
    """An execution can match its card type, exact tool name, and recorded status."""
    activity = entry.get('activity_type') or ''
    event = entry.get('event_type')
    execution = entry.get('execution') or {}
    item = entry.get('item') or {}
    values = set()
    if entry.get('kind') == 'message':
        role = entry.get('role')
        values.add({'user': 'User messages', 'assistant': 'Assistant messages'}.get(role, 'Messages'))
        if event == 'assistant_error':
            values.add('Errors')
    elif activity == 'ToolExecution' or activity.endswith('ToolCall'):
        values.add('Tool calls')
    elif activity in ('CommandExecution', 'RUN_COMMAND'):
        values.add('Commands')
    elif activity in ('FileChange', 'file_change'):
        values.add('File changes')
    elif activity == 'file_attachment':
        values.add('Attachments')
    elif activity == 'ERROR_MESSAGE':
        values.add('Errors')
    if entry.get('attachments') or entry.get('file_refs'):
        values.add('Attachments')
    if activity:
        detail = entry.get('part_type') if activity == 'raw_part' else activity
        values.add(f'Type: {detail or activity}')
    tool = execution.get('tool') or item.get('tool') or entry.get('tool_name')
    if isinstance(tool, str) and tool.strip():
        values.add(f'Tool: {tool}')
        if tool.casefold() in ('bash', 'powershell', 'run_command', 'exec_command'):
            values.add('Commands')
        if tool.casefold() in ('edit', 'write', 'multiedit', 'apply_patch'):
            values.add('File changes')
    status = execution.get('recorded_status')
    if status is None:
        status = execution.get('status') if execution.get('status') is not None else entry.get('status')
    if isinstance(status, (str, int)) and str(status).strip():
        values.add(f'Status: {status}')
    return frozenset(values)


class TranscriptIndex:
    def __init__(self, turns):
        self.turns = []
        self.turn_filters = []
        all_values = set()
        self.prompt_for = {}
        self.response_counts = {}
        for turn in turns:
            records = []
            turn_values = set()
            prompt = None
            for entry in turn['entries']:
                if entry.get('kind') == 'message' and entry.get('role') == 'user':
                    prompt = entry
                elif prompt is not None:
                    self.prompt_for[id(entry)] = prompt
                    key = id(prompt)
                    self.response_counts[key] = self.response_counts.get(key, 0) + 1
                fields = ('text', 'command', 'timestamp', 'ordinal', 'role', 'phase', 'activity_type',
                          'status', 'cwd', 'pid', 'exit_code', 'correlation_note', 'file_refs', 'attachments',
                          'session_id', 'message_id', 'part_id', 'call_id', 'part_type', 'evidence')
                item = entry.get('item') or {}
                values = [entry[k] for k in fields if k in entry]
                values.extend(item[k] for k in ('aggregated_output', 'changes', 'stdout', 'stderr',
                              'server', 'tool', 'name', 'arguments', 'result', 'error') if k in item)
                execution = entry.get('execution') or {}
                values.extend(execution[k] for k in ('tool', 'arguments', 'partial_input', 'status',
                              'output', 'error', 'metadata', 'start_label', 'end_label') if k in execution)
                facets = filter_values(entry)
                turn_values.update(facets)
                records.append((entry, facets, '\n'.join(map(safe_text, values)).casefold()))
            self.turns.append((turn['title'], records))
            self.turn_filters.append(self._choices(turn_values))
            all_values.update(turn_values)
        self.filters = self._choices(all_values)

    @staticmethod
    def _choices(values):
        return (ALL_ENTRIES, *sorted(values, key=lambda v: (':' in v, v.casefold(), v)))

    def matches(self, query, kind, turn_index=None, *, cancelled=None):
        terms = query.casefold().split()
        indices = range(len(self.turns)) if turn_index is None else (turn_index,)
        for index in indices:
            title, records = self.turns[index]
            for entry, facets, text in records:
                if cancelled is not None and cancelled.is_set():
                    return
                if (kind == ALL_ENTRIES or kind in facets) and all(t in text for t in terms):
                    yield index, title, entry
