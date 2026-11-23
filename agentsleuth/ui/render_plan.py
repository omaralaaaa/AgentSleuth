"""Prepare an ordered transcript and styled spans using only plain Python data."""

from ..core.utils import safe_text
from .powershell import command_parts, is_powershell


def build_plan(index, query, kind, turn, tree, collapsed, cached, cancelled):
    matches = index.matches(query, kind, turn, cancelled=cancelled)
    if not tree:
        matches = sorted(matches, key=lambda match: match[2]['ordinal'])
    rows = []
    styles = {}
    previous_turn = current_prompt = None
    total = hidden = 0
    for turn_id, _, entry in matches:
        if cancelled.is_set():
            return None
        total += 1
        if tree:
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
        if key not in cached and entry.get('activity_type') == 'CommandExecution':
            command = safe_text(entry.get('command'))
            if is_powershell((entry.get('item') or {}).get('command'), command):
                styles[key] = command_parts(command)
    if not rows:
        rows.append(('empty', 'No matching entries in this view.'))
    return rows, {key for key, _ in rows}, total, hidden, styles
