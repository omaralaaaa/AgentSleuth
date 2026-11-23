"""Correlate Claude tool calls and results by ID within one transcript branch."""

from collections import defaultdict

from .records import string_value


def _call_sources(entry):
    return [source['raw'].get('uuid') for source in entry['raw']['calls']]


def _match(candidates, result, by_uuid):
    if len(candidates) == 1:
        return candidates[0]
    raw = result['source']['raw']
    parent = string_value(raw.get('sourceToolAssistantUUID')) or string_value(raw.get('parentUuid'))
    visited = set()
    while parent and parent not in visited:
        visited.add(parent)
        matches = [entry for entry in candidates if parent in _call_sources(entry)]
        if matches:
            return matches[0] if len(matches) == 1 else None
        parent = string_value(by_uuid.get(parent, {}).get('parentUuid'))
    return None


def correlate(calls, results, references):
    by_id = defaultdict(list)
    for entry in calls:
        if entry['call_id']:
            by_id[entry['call_id']].append(entry)
    by_uuid = {raw['uuid']: raw for ref in references if (raw := ref['raw'])
               and string_value(raw.get('uuid'))}
    unmatched = []
    for result in results:
        candidates = by_id.get(result['call_id'], ())
        entry = _match(candidates, result, by_uuid) if candidates else None
        if entry is None:
            unmatched.append(result)
        else:
            entry['raw']['results'].append(result)
    return unmatched
