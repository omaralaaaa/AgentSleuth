"""Read and inspect OpenCode SQLite evidence without writing to it."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


LEGACY_COLUMNS = {
    'session': {'id'},
    'message': {'id', 'session_id'},
    'part': {'id', 'message_id'},
}
SKIPPED_PART_TYPES = {'step-start', 'reasoning', 'step-finish'}
ORDER_FIELDS = ('ordinal', 'sequence', 'sequence_number', 'sequencenumber', 'seq',
                'position', 'message_index', 'messageindex', 'part_index', 'partindex',
                'index', 'order')


def _legacy_schema(connection):
    tables = {name.lower() for (name,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    for table, required in LEGACY_COLUMNS.items():
        if table not in tables:
            raise ValueError(f'Unsupported OpenCode database: missing table {table!r}')
        columns = {row['name'].lower() for row in connection.execute(f'PRAGMA table_info("{table}")')}
        if missing := required - columns:
            raise ValueError(f'Unsupported OpenCode database: {table} is missing {", ".join(sorted(missing))}')


@contextmanager
def open_evidence(path: Path):
    uri = path.expanduser().resolve().as_uri() + '?mode=ro'
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        _legacy_schema(connection)
        yield connection
    finally:
        connection.close()


def load_threads(path: Path):
    """Discover session titles and identifiers without reading messages or parts."""
    with open_evidence(path) as connection:
        sessions = []
        for row in connection.execute('SELECT * FROM "session"'):
            fields = {key.lower(): row[key] for key in row.keys()}
            ident = fields['id']
            sessions.append({
                'id': ident,
                'name': str(fields.get('title') or '').strip() or f'Unnamed conversation ({ident})',
                'cwd': str(fields.get('directory') or ''),
                'time_created': fields.get('time_created'),
                'time_updated': fields.get('time_updated'),
                'raw': dict(row),
            })
    def last_active(session):
        value = session['time_updated']
        if value is None:
            value = session['time_created']
        return isinstance(value, str), value if isinstance(value, (int, float, str)) else 0

    sessions.sort(key=lambda session: str(session['id']))
    sessions.sort(key=last_active, reverse=True)
    return sessions


def _select_parts(connection, session_id):
    query = ('SELECT p.* FROM "message" AS m JOIN "part" AS p ON p.message_id = m.id '
             'WHERE m.session_id = ?')
    columns = {row['name'].lower() for row in connection.execute('PRAGMA table_info("part")')}
    if 'data' not in columns:
        return connection.execute(query, (session_id,))

    types = sorted(SKIPPED_PART_TYPES)
    type_parameters = ', '.join('?' for _ in types)
    order_parameters = ', '.join('?' for _ in ORDER_FIELDS)
    column_order = ''.join(f' OR p."{key}" IS NOT NULL' for key in ORDER_FIELDS if key in columns)
    # Numbered rows can occupy the original ordering slots of surviving events.
    # Let the parser keep those slots, while SQLite drops unnumbered skipped rows.
    filtered = f'''
        AND CASE WHEN json_valid(CAST(p.data AS TEXT)) THEN
            CASE WHEN json_extract(CAST(p.data AS TEXT), '$.type') IN ({type_parameters}) THEN
                0 {column_order}
                OR EXISTS (SELECT 1 FROM json_each(CAST(p.data AS TEXT))
                           WHERE lower(key) IN ({order_parameters})
                              OR (key = 'type' AND COALESCE(value NOT IN ({type_parameters}), 1)))
            ELSE 1 END
        ELSE 1 END
    '''
    try:
        return connection.execute(query + filtered, (session_id, *types, *ORDER_FIELDS, *types))
    except sqlite3.OperationalError as error:
        if str(error) not in {'no such function: json_valid', 'no such function: json_extract',
                              'no such table: json_each'}:
            raise
        return connection.execute(query, (session_id,))


def read_conversation(path: Path, session_id, progress=None):
    """Read both record sets from the same SQLite snapshot."""
    with open_evidence(path) as connection:
        if connection.execute('SELECT 1 FROM "session" WHERE id = ?', (session_id,)).fetchone() is None:
            raise ValueError(f'OpenCode session {session_id!r} is no longer present in the database')
        messages = []
        messages_with_parts = set()
        # Keep the presence flag separate from the raw message record.
        for row in connection.execute(
            'SELECT m.*, EXISTS (SELECT 1 FROM "part" AS p WHERE p.message_id = m.id) '
            'FROM "message" AS m WHERE m.session_id = ?', (session_id,)
        ):
            messages.append(dict(zip(row.keys()[:-1], row[:-1])))
            if row[-1]:
                messages_with_parts.add(row['id'])
        parts = []
        for number, row in enumerate(_select_parts(connection, session_id), 1):
            parts.append(dict(row))
            if progress and number % 500 == 0:
                progress(f'Reading OpenCode evidence · {number:,} parts')
    return messages, parts, messages_with_parts
