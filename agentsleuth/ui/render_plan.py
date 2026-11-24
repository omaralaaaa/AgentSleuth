"""Prepare an ordered transcript and styled spans using only plain Python data."""

from ..core.utils import safe_text
from .powershell import command_parts, is_powershell
from .shell import shell_arguments, shell_command_parts


def build_plan(index, query, kind, turn, collapsed, cached, cancelled):
    rows = []
    styles = {}
    previous_turn = current_prompt = None
    total = hidden = 0
    for turn_id, _, entry in index.matches(query, kind, turn, cancelled=cancelled):
        if cancelled.is_set():
            return None
        total += 1
        if turn_id != previous_turn:
            rows.append((('turn', turn_id), f'Turn {turn_id + 1}'))
            previous_turn = turn_id
            current_prompt = None
        prompt = index.prompt_for.get(id(entry))
        if prompt is not None:
            if current_prompt != id(prompt):
                rows.append((id(prompt), prompt))
                current_prompt = id(prompt)
            if current_prompt in collapsed:
                hidden += 1
                continue
        elif entry.get('role') == 'user':
            current_prompt = id(entry)
        key = id(entry)
        rows.append((key, entry))
        if key in cached:
            continue
        if entry.get('activity_type') == 'CommandExecution':
            command = safe_text(entry.get('command'))
            if is_powershell((entry.get('item') or {}).get('command'), command):
                styles[key] = command_parts(command)
        elif arguments := shell_arguments(entry):
            styles[key] = shell_command_parts(entry['execution']['tool'], arguments['command'])
    if not rows:
        rows.append(('empty', 'No matching entries in this view.'))
    return rows, {key for key, _ in rows}, total, hidden, styles
