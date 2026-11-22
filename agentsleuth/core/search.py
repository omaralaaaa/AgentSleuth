"""Search normalized transcript fields without consulting Tk widgets or evidence files."""

from .utils import safe_text


ENTRY_TYPES = ('All entries', 'User messages', 'Assistant messages', 'Commands',
               'File changes', 'Tool calls', 'Other activities')


def category(entry):
    if entry.get('kind') == 'message':
        return 'User messages' if entry.get('role') == 'user' else 'Assistant messages'
    activity = entry.get('activity_type', '')
    if activity.endswith('ToolCall'):
        return 'Tool calls'
    return {'CommandExecution': 'Commands', 'FileChange': 'File changes'}.get(activity, 'Other activities')


class TranscriptIndex:
    def __init__(self, turns):
        self.turns = []
        self.prompt_for = {}
        self.response_counts = {}
        for turn in turns:
            records = []
            prompt = None
            for entry in turn['entries']:
                if entry.get('kind') == 'message' and entry.get('role') == 'user':
                    prompt = entry
                elif prompt is not None:
                    self.prompt_for[id(entry)] = prompt
                    key = id(prompt)
                    self.response_counts[key] = self.response_counts.get(key, 0) + 1
                fields = ('text', 'command', 'timestamp', 'ordinal', 'role', 'phase', 'activity_type',
                          'status', 'cwd', 'pid', 'exit_code', 'correlation_note', 'file_refs', 'attachments')
                item = entry.get('item') or {}
                values = [entry[k] for k in fields if k in entry]
                values.extend(item[k] for k in ('aggregated_output', 'changes', 'stdout', 'stderr',
                              'server', 'tool', 'name', 'arguments', 'result', 'error') if k in item)
                records.append((entry, category(entry), '\n'.join(map(safe_text, values)).casefold()))
            self.turns.append((turn['title'], records))

    def matches(self, query, kind, turn_index=None):
        terms = query.casefold().split()
        indices = range(len(self.turns)) if turn_index is None else (turn_index,)
        for index in indices:
            title, records = self.turns[index]
            for entry, category_name, text in records:
                if (kind == ENTRY_TYPES[0] or category_name == kind) and all(t in text for t in terms):
                    yield index, title, entry
