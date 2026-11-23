"""Read Codex state_5.sqlite and enumerate conversation threads."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path


def _sqlite_ro(path: Path):
    """Read the SQLite state DB without running queries that modify its data."""
    uri = path.resolve().as_uri() + '?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con

def _first(row: dict, *names, default=None):
    lower = {k.lower(): v for k, v in row.items()}
    for n in names:
        if (v := lower.get(n.lower())) is not None:
            return v
    return default

def _sandbox_label(raw):
    if isinstance(raw, (dict, list)):
        obj = raw
    elif raw is None or raw == '':
        return 'Unknown (not in threads table)'
    else:
        try:
            obj = json.loads(str(raw))
        except (json.JSONDecodeError, ValueError, TypeError):
            return str(raw)
    if isinstance(obj, dict):
        policy = (obj.get('type') or obj.get('policy') or obj.get('sandbox_mode')
                  or obj.get('sandboxMode') or 'unknown')
        extras = []
        if obj.get('writable_roots'):
            extras.append('Writable: ' + ', '.join(map(str, obj['writable_roots'])))
        if 'network_access' in obj:
            extras.append('Network: ' + str(obj['network_access']))
    else:
        policy, extras = str(obj), []
    friendly = {
        'danger-full-access': 'Full access',
        'workspace-write': 'Workspace write',
        'read-only': 'Read only',
    }.get(str(policy).lower(), str(policy))
    return f'{friendly} ({policy})' + ('  ·  ' + '  ·  '.join(extras) if extras else '')

def load_threads(db_path: Path):
    """Discover native 'threads' rows, including title, rollout_path, cwd and policy."""
    db_path = db_path.expanduser().resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f'SQLite database does not exist: {db_path}')
    with closing(_sqlite_ro(db_path)) as con:
        names = [r['name'] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        threads_table = next((t for t in names if t.lower() == 'threads'), None)
        if not threads_table:
            raise ValueError("Table 'threads' was not found. Available tables: " + ', '.join(names))
        # SQLite identifiers come only from sqlite_master, not user input.
        quoted = '"' + threads_table.replace('"', '""') + '"'
        columns = [r['name'] for r in con.execute(f'PRAGMA table_info({quoted})')]
        order_col = next((c for c in ('updated_at', 'last_active_at', 'last_used_at', 'created_at', 'id')
                          if c in columns), None)
        order_sql = f' ORDER BY "{order_col}" DESC' if order_col else ''
        rows = [dict(r) for r in con.execute(f'SELECT * FROM {quoted}' + order_sql)]
    results = []
    for idx, row in enumerate(rows):
        ident = str(_first(row, 'id', 'thread_id', 'session_id', 'uuid', default=f'row-{idx}'))
        # The SQLite `name` column is the conversation display name.
        # `title` is often derived from the first user prompt and must not be used here.
        name = str(_first(row, 'name', default='') or '').strip()
        display_name = name or f'Unnamed conversation ({ident[:12]})'
        results.append({
            'id': ident,
            'name': display_name,
            'export_title': name,
            'rollout_path': str(_first(row, 'rollout_path', 'rollout_file', 'path', default='') or ''),
            'cwd': str(_first(row, 'cwd', 'working_directory', 'workdir', default='') or ''),
            'sandbox_policy': _first(row, 'sandbox_policy', 'sandbox_mode'),
            'permissions': _sandbox_label(_first(row, 'sandbox_policy', 'sandbox_mode')),
            'approval_policy': _first(row, 'approval_policy'),
            'raw': row,
        })
    return results
