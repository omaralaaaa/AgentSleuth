"""Human-readable formatting for tool arguments and outputs."""

import json

from .utils import safe_text


def _format_code(value):
    text = safe_text(value)
    if not text:
        return ''
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return text

def _pretty_output(text):
    """Make JSON output segments readable without displaying Python reprs."""
    if not text:
        return ''
    segments = []
    for part in str(text).splitlines():
        stripped = part.strip()
        if stripped.startswith(('{', '[')) and stripped.endswith(('}', ']')):
            try:
                value = json.loads(stripped)
                if isinstance(value, dict) and ('exit_code' in value or 'output' in value):
                    desc = []
                    for field in ('exit_code', 'wall_time_seconds', 'chunk_id', 'original_token_count'):
                        if field in value:
                            desc.append(f'{field}: {value[field]}')
                    if 'output' in value:
                        desc.append('OUTPUT:\n' + safe_text(value['output']))
                    segments.append('\n'.join(desc))
                    continue
                segments.append(json.dumps(value, indent=2, ensure_ascii=False))
                continue
            except json.JSONDecodeError:
                pass
        segments.append(part)
    return '\n'.join(segments)
