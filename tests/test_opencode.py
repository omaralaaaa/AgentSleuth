import base64
import hashlib
import json
import sqlite3
import tempfile
import threading
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentsleuth.parsers import opencode
from agentsleuth.parsers.opencode import database, reconstruction
from agentsleuth.parsers.opencode.database import open_evidence
from agentsleuth.ui.app import App


SCHEMA = """
CREATE TABLE session (id TEXT PRIMARY KEY, title TEXT, directory TEXT,
                      time_created INTEGER, time_updated INTEGER);
CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER,
                      time_updated INTEGER, data TEXT, ordinal INTEGER);
CREATE TABLE part (id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT,
                   time_created INTEGER, time_updated INTEGER, data TEXT, sequence INTEGER);
CREATE INDEX part_message ON part (message_id);
"""


def build_database(path, output='recorded output'):
    """Insert records out of timeline order and a second, independent session."""
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA)
        db.executemany('INSERT INTO session VALUES (?, ?, ?, ?, ?)', [
            ('other', 'Other title', '/elsewhere', 10, 20),
            ('session', 'Recorded session title', '/recorded/workdir', 1, 100),
        ])

        def message(message_id, session_id, created, role, ordinal=None, **data):
            db.execute('INSERT INTO message VALUES (?, ?, ?, ?, ?, ?)',
                       (message_id, session_id, created, 100, json.dumps(dict(role=role, **data)), ordinal))

        def part(part_id, message_id, created, data, sequence=None, session='session'):
            db.execute('INSERT INTO part VALUES (?, ?, ?, ?, ?, ?, ?)',
                       (part_id, message_id, session, created, 100,
                        json.dumps(data) if not isinstance(data, str) else data, sequence))

        message('a-reply', 'session', 4, 'assistant', parentID='z-prompt')
        message('b-user', 'session', 20, 'user')
        message('b-assistant', 'session', 20, 'assistant', parentID='z-prompt', providerID='fixture',
                error={'name': 'APIError', 'data': {'message': 'This API key has expired.',
                                                   'statusCode': 401, 'responseBody': 'Example response',
                                                   'responseHeaders': {'content-type': 'text/plain'}}})
        message('z-prompt', 'session', 1, 'user', model={'modelID': 'fixture'})
        message('a-other', 'other', 0, 'assistant')
        part('a-other-part', 'a-other', 1, dict(type='text', text='Other session'))
        part('orphan', 'missing-message', 0, dict(type='text', text='Orphan part'))
        part('z-prompt', 'z-prompt', 1, dict(type='text', text='Original question'))
        part('attachment', 'z-prompt', 2, dict(type='file', filename='example.txt', url='file:///example.txt'))
        part('assistant-text-2', 'a-reply', 5, dict(type='text', text='Final response'), 7)
        part('assistant-text-1', 'a-reply', 12, dict(type='text', text='First response'), 1)
        part('step-start', 'a-reply', 4, dict(type='step-start'))
        part('reasoning', 'a-reply', 7, dict(type='reasoning', text='Recorded reasoning'), 2)
        part('unnumbered-reasoning', 'a-reply', 13, dict(type='reasoning', text='Omitted reasoning'))
        part('step-finish', 'a-reply', 14, dict(type='step-finish'))
        part('bash-pending', 'a-reply', 6, dict(type='tool', tool='bash', callID='bash-call',
                                               state=dict(status='pending', input={'command': 'pwd'})), 3)
        part('bash-completed', 'a-reply', 8, dict(type='tool', tool='bash', callID='bash-call',
                                                 state=dict(status='completed', output=output,
                                                            metadata={'count': 0}, time={'start': 6, 'end': 8})), 4)
        part('failed', 'a-reply', 9, dict(type='tool', tool='read', callID='read-call',
                                         state=dict(status='error', error='Permission denied')), 5)
        part('running', 'a-reply', 10, dict(type='tool', tool='search', state={'status': 'running'}), 6)
        part('pending', 'a-reply', 14,
             dict(type='tool', tool='search', state={'status': 'pending', 'raw': '{"query":'}),
             8, session='other')  # Association comes from the source message, preserving this mismatch.
        part('patch', 'a-reply', 15, dict(type='patch', files=['example.txt']))
        part('unknown', 'a-reply', 16, dict(type='future-part', value={'kept': [0, False, None]}))
        part('malformed', 'a-reply', 17, '{not json')
        part('missing-type', 'a-reply', 18, [None, 3])
        part('no-status', 'a-reply', 19, dict(type='tool', state=[]))
        part('more', 'b-user', 20, dict(type='text', text='Follow-up question'))


class OpenCodeTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = Path(directory.name) / 'opencode # evidence.db'
        build_database(self.db)

    def parse(self, index=0):
        return opencode.reconstruct_from_thread(self.db, opencode.load_threads(self.db)[index])

    def test_session_discovery_and_read_only_access(self):
        before = self.db.read_bytes()
        sessions = opencode.load_threads(self.db)
        self.assertEqual([(row['id'], row['name']) for row in sessions], [
            ('session', 'Recorded session title'), ('other', 'Other title'),
        ])
        self.assertEqual(sessions[0]['cwd'], '/recorded/workdir')
        self.assertEqual((sessions[0]['time_created'], sessions[0]['time_updated']), (1, 100))
        with open_evidence(self.db) as connection:
            self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0], 1)
            with self.assertRaisesRegex(sqlite3.OperationalError, 'readonly'):
                connection.execute('UPDATE session SET title = ?', ('unexpected',))
        self.parse()
        self.assertEqual(self.db.read_bytes(), before)

    def test_uploaded_files_extract_and_link_to_their_message(self):
        binary = bytes(range(256))
        encoded = base64.b64encode(binary).decode()
        uploads = {
            'embedded': dict(filename='../sample.pdf', mime='application/pdf',
                             url='data:application/pdf;base64,' + encoded),
            'text-file': dict(filename='sample.txt', url='data:text/plain;charset=utf-8,caf%C3%A9+%0A'),
            'bad-file': dict(filename='broken.bin', url='data:application/octet-stream;base64,?!'),
            'external': dict(url='https://example.invalid/remote%20name.png'),
        }
        with closing(sqlite3.connect(self.db)) as db, db:
            for key, fields in uploads.items():
                db.execute('INSERT INTO part VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (key, 'z-prompt', 'session', 3, 3, json.dumps(dict(type='file', **fields)), None))
        before = self.db.read_bytes()
        root = self.db.parent / 'results'
        result = opencode.reconstruct_from_thread(self.db, opencode.load_threads(self.db)[0], root)
        entries = result['turns'][0]['entries']
        prompt = next(e for e in entries if e['event_type'] == 'user_prompt')
        files = {a['part_id']: a for a in prompt['file_links']}
        self.assertEqual(set(files), set(uploads) | {'attachment'})
        self.assertEqual(files['embedded']['filename'], 'sample.pdf')
        self.assertEqual(files['embedded']['sha256'], hashlib.sha256(binary).hexdigest())
        target = Path(files['embedded']['saved_path'])
        self.assertTrue(target.resolve().is_relative_to(root.resolve()))
        self.assertEqual(target.read_bytes(), binary)
        self.assertEqual(Path(files['text-file']['saved_path']).read_bytes(), 'café+\n'.encode())
        self.assertEqual(files['external']['filename'], 'remote name.png')
        for key in ('attachment', 'external', 'bad-file'):
            self.assertIsNone(files[key]['saved_path'])
        self.assertEqual(result['summary']['attachments'], 2)
        self.assertEqual(result['attachment_failures'][0]['part_id'], 'bad-file')
        self.assertEqual(self.db.read_bytes(), before)

    def test_message_and_part_order_and_relationships(self):
        result = self.parse()
        messages = result['messages']
        self.assertEqual([message['id'] for message in messages],
                         ['z-prompt', 'a-reply', 'b-assistant', 'b-user'])
        self.assertEqual(messages[0]['data']['model'], {'modelID': 'fixture'})
        self.assertEqual(messages[1]['data']['parentID'], 'z-prompt')
        self.assertEqual(messages[1]['time_updated'], 100)
        self.assertEqual([part['id'] for part in messages[1]['parts']], [
            'assistant-text-1', 'bash-pending', 'bash-completed', 'failed', 'running',
            'assistant-text-2', 'pending', 'patch', 'unknown', 'malformed', 'missing-type', 'no-status',
        ])
        self.assertEqual(messages[1]['parts'][6]['session_id'], 'other')
        self.assertEqual(messages[1]['parts'][0]['message_id'], 'a-reply')
        self.assertEqual(messages[1]['parts'][0]['sequence'], 1)
        entries = [entry for turn in result['turns'] for entry in turn['entries']]
        self.assertEqual([entry['text'] for entry in entries if entry['kind'] == 'message'], [
            'Original question', 'First response', 'Final response', 'This API key has expired.',
            'Follow-up question',
        ])
        self.assertEqual([entry['event_type'] for entry in entries][:6], [
            'user_prompt', 'file_attachment', 'assistant_response', 'execution', 'execution', 'execution',
        ])
        self.assertTrue(all(entry['session_id'] == 'session' and entry['agent'] == 'opencode'
                            for entry in entries))
        self.assertEqual([message['id'] for message in self.parse(1)['messages']], ['a-other'])

    def test_skipped_parts_never_enter_normalization(self):
        with patch.object(reconstruction, '_record', wraps=reconstruction._record) as normalize:
            result = self.parse()
        normalized_ids = {call.args[0]['id'] for call in normalize.call_args_list
                          if call.kwargs.get('part')}
        self.assertTrue({'step-start', 'reasoning', 'unnumbered-reasoning', 'step-finish'}
                        .isdisjoint(normalized_ids))
        self.assertEqual(result['summary']['parts'], len(normalized_ids))
        self.assertIn('patch', normalized_ids)

    def test_sql_excludes_unsequenced_skips_and_preserves_ambiguous_json(self):
        with open_evidence(self.db) as connection:
            try:
                connection.execute("SELECT json_extract('{}', '$.type') FROM json_each('{}')").fetchall()
            except sqlite3.OperationalError as error:
                self.skipTest(str(error))
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO part VALUES (?, ?, ?, ?, ?, ?, ?)',
                       ('duplicate-type', 'a-reply', 'session', 18, 18,
                        '{"type":"reasoning","type":"text","text":"Retained text"}', None))
        _, parts, _ = database.read_conversation(self.db, 'session')
        ids = {part['id'] for part in parts}
        self.assertTrue({'step-start', 'unnumbered-reasoning', 'step-finish'}.isdisjoint(ids))
        self.assertTrue({'malformed', 'missing-type', 'unknown', 'duplicate-type'}.issubset(ids))

    def test_missing_sqlite_json_support_falls_back_to_parser_filter(self):
        class ConnectionWithoutJSON(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                if 'json_valid(' in sql:
                    raise sqlite3.OperationalError('no such function: json_valid')
                return super().execute(sql, parameters)

        expected = self.parse()
        thread = expected['thread']
        connection = sqlite3.connect(self.db.as_uri() + '?mode=ro', uri=True,
                                     factory=ConnectionWithoutJSON)
        connection.row_factory = sqlite3.Row
        with patch.object(database, 'open_evidence', return_value=closing(connection)):
            self.assertEqual(opencode.reconstruct_from_thread(self.db, thread), expected)

    def test_skips_keep_mixed_ordering_and_do_not_create_empty_cards(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executemany('INSERT INTO message VALUES (?, ?, ?, ?, ?, ?)', [
                ('mixed', 'session', 30, 30, '{"role":"assistant"}', None),
                ('only-skipped', 'session', 40, 40, '{"role":"assistant"}', None),
            ])
            db.executemany('INSERT INTO part VALUES (?, ?, ?, ?, ?, ?, ?)', [
                ('slot', 'mixed', 'session', 30, 30, '{"type":"step-start","Sequence":5}', None),
                ('unnumbered', 'mixed', 'session', 31, 31, '{"type":"text","text":"Second"}', None),
                ('numbered', 'mixed', 'session', 32, 32, '{"type":"text","text":"First"}', 1),
                ('end', 'only-skipped', 'session', 40, 40, '{"type":"step-finish"}', None),
            ])
        result = self.parse()
        entries = [entry for turn in result['turns'] for entry in turn['entries']]
        mixed = [entry for entry in entries if entry['message_id'] == 'mixed']
        self.assertEqual([entry['part_id'] for entry in mixed], ['numbered', 'unnumbered'])
        self.assertEqual([entry['timestamp'] for entry in mixed], [32, 31])
        self.assertFalse(any(entry['message_id'] == 'only-skipped' for entry in entries))

    def test_executions_preserve_tool_states_and_raw_evidence(self):
        result = self.parse()
        entries = [entry for turn in result['turns'] for entry in turn['entries'] if 'execution' in entry]
        self.assertEqual([entry['execution']['status'] for entry in entries],
                         ['completed', 'failed', 'running', 'pending', None])
        merged = entries[0]
        execution = merged['execution']
        self.assertEqual((merged['call_id'], merged['part_id']), ('bash-call', 'bash-pending'))
        self.assertEqual(execution['tool'], 'bash')
        self.assertEqual(execution['arguments'], {'command': 'pwd'})
        self.assertEqual(execution['command'], 'pwd')
        self.assertEqual(execution['output'], 'recorded output')
        self.assertEqual(execution['metadata'], {'count': 0})
        self.assertEqual((execution['start'], execution['end']), (6, 8))
        self.assertEqual([row['id'] for row in merged['raw']['parts']], ['bash-pending', 'bash-completed'])
        self.assertEqual(entries[1]['execution']['error'], 'Permission denied')
        self.assertEqual(entries[1]['execution']['recorded_status'], 'error')
        self.assertIsNone(entries[2]['execution']['output'])
        self.assertEqual(entries[3]['execution']['partial_input'], '{"query":')

    def test_missing_and_unrecognized_part_data_remain_evidence(self):
        result = self.parse()
        entries = {entry['part_id']: entry for turn in result['turns'] for entry in turn['entries']}
        self.assertEqual(entries['unknown']['event_type'], 'raw_part')
        self.assertEqual(json.loads(entries['unknown']['evidence'])['value'], {'kept': [0, False, None]})
        self.assertEqual(entries['malformed']['evidence'], '{not json')
        self.assertEqual(json.loads(entries['missing-type']['evidence']), [None, 3])
        self.assertEqual(entries['patch']['event_type'], 'file_change')

    def test_assistant_error_prefers_readable_text_and_retains_the_raw_message(self):
        cases = [
            ({'data': {'message': 'Preferred text', 'responseBody': 'Recorded body'},
              'message': 'Fallback text', 'name': 'APIError'}, 'Preferred text'),
            ({'data': {'message': []}, 'message': 'Fallback text', 'name': 'APIError'}, 'Fallback text'),
            ({'data': [], 'message': ' ', 'name': 'APIError'}, 'APIError'),
            ({'name': {}}, 'No error message recorded.'),
            ('malformed error', 'No error message recorded.'),
        ]
        for error, text in cases:
            with self.subTest(error=error):
                data = {'role': 'assistant', 'error': error, 'parentID': 'z-prompt'}
                with closing(sqlite3.connect(self.db)) as db, db:
                    db.execute('UPDATE message SET data = ? WHERE id = ?',
                               (json.dumps(data), 'b-assistant'))
                error_entry, = [entry for turn in self.parse()['turns'] for entry in turn['entries']
                                if entry['message_id'] == 'b-assistant']
                self.assertEqual(error_entry['event_type'], 'assistant_error')
                self.assertEqual(error_entry['text'], text)
                self.assertEqual(error_entry['timestamp'], 20)
                self.assertEqual(json.loads(error_entry['raw']['message']['data']), data)
                self.assertNotIn('evidence', error_entry)

    def test_schema_is_verified_and_optional_columns_may_be_absent(self):
        other = self.db.with_name('other.db')
        with closing(sqlite3.connect(other)) as db, db:
            db.executescript('CREATE TABLE session (id TEXT); INSERT INTO session VALUES (\'s\');')
        with self.assertRaisesRegex(ValueError, "missing table 'message'"):
            opencode.load_threads(other)
        with closing(sqlite3.connect(other)) as db, db:
            db.executescript('CREATE TABLE message (id TEXT, session_id TEXT);'
                             'CREATE TABLE part (id TEXT, message_id TEXT);'
                             'INSERT INTO message VALUES (\'m\', \'s\');'
                             'INSERT INTO part VALUES (\'p\', \'m\');')
        session = opencode.load_threads(other)[0]
        self.assertIsNone(session['time_created'])
        result = opencode.reconstruct_from_thread(other, session)
        entry = result['turns'][0]['entries'][0]
        self.assertIsNone(entry['timestamp'])
        self.assertIsNone(entry['role'])
        self.assertEqual(json.loads(entry['evidence']), {'id': 'p', 'message_id': 'm'})

    def test_explicit_message_ordinal_precedes_timestamp(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE message SET ordinal = ? WHERE id = ?', (3, 'z-prompt'))
            db.execute('UPDATE message SET ordinal = ? WHERE id = ?', (1, 'a-reply'))
        messages = self.parse()['messages']
        self.assertEqual([message['id'] for message in messages],
                         ['a-reply', 'z-prompt', 'b-assistant', 'b-user'])

    def test_part_order_uses_json_time_and_stable_ids_when_creation_is_missing(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE part SET time_created = ? WHERE id = ?', (3, 'z-prompt'))
            for part_id, created in [('attachment', 3), ('b-reference', 1)]:
                evidence = json.dumps({'type': 'file', 'time': {'start': created}})
                db.execute('INSERT OR REPLACE INTO part VALUES (?, ?, ?, ?, ?, ?, ?)',
                           (part_id, 'z-prompt', 'session', None, 100, evidence, None))
        parts = self.parse()['messages'][0]['parts']
        self.assertEqual([part['id'] for part in parts], ['b-reference', 'attachment', 'z-prompt'])
        self.assertEqual([part['timestamp'] for part in parts], [1, 3, 3])


class OpenCodeViewerTest(unittest.TestCase):
    def app(self, **providers):
        try:
            root = App(**providers)
        except tk.TclError as error:
            if 'display' in str(error):
                self.skipTest(str(error))
            raise
        self.addCleanup(root.destroy)
        root.geometry('1000x700+10000+10000')
        return root

    def wait_for(self, app, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            app.update()
            time.sleep(.01)
        self.assertTrue(condition())
        app.update()

    def test_agent_workers_have_isolated_jobs_views_errors_and_caches(self):
        release_codex, release_old_session = threading.Event(), threading.Event()
        codex_started, old_session_started = threading.Event(), threading.Event()
        calls = []

        def load_codex(_path):
            calls.append(('codex', 'load', threading.get_ident()))
            return [dict(id='session', name='Codex title', cwd='', rollout_path='')]

        def parse_codex(_path, thread, _output, progress):
            calls.append(('codex', thread['id'], threading.get_ident()))
            codex_started.set()
            release_codex.wait(5)
            progress('Codex parse finishing')
            return dict(turns=[dict(title='Codex turn', entries=[
                dict(kind='message', role='user', ordinal=1, text='Codex transcript')])],
                summary=dict(turns=1, activities=0))

        def load_opencode(path):
            calls.append(('opencode', 'load', threading.get_ident()))
            return opencode.load_threads(path)

        def parse_opencode(path, thread, output, progress):
            calls.append(('opencode', thread['id'], threading.get_ident()))
            if thread['id'] == 'session' and not old_session_started.is_set():
                old_session_started.set()
                release_old_session.wait(5)
                progress('Stale OpenCode progress')
            return opencode.reconstruct_from_thread(path, thread, output, progress)

        codex = SimpleNamespace(name='Codex', source_label='Database', source_hint='Choose Codex evidence',
                                filetypes=[], load_threads=load_codex, reconstruct_from_thread=parse_codex)
        provider = SimpleNamespace(name=opencode.name, source_label=opencode.source_label,
                                   source_hint=opencode.source_hint, filetypes=opencode.filetypes,
                                   uses_output_directory=False, load_threads=load_opencode,
                                   reconstruct_from_thread=parse_opencode)
        root = self.app(parser=codex, opencode_parser=provider)
        self.addCleanup(release_codex.set)
        self.addCleanup(release_old_session.set)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'opencode.db'
            build_database(source)
            for pane in (root.codex, root.opencode):
                pane.db_path.set(str(source))
                pane._load()
            self.wait_for(root, lambda: not root.codex._working and not root.opencode._working)
            self.assertCountEqual([(agent, action) for agent, action, _ in calls],
                                  [('codex', 'load'), ('opencode', 'load')])
            self.assertEqual(root.opencode.conversations.item('0', 'values')[1], 'Recorded session title')
            self.assertIsNone(root.opencode.result)
            root.codex.conversations.selection_set('0')
            self.wait_for(root, codex_started.is_set)
            root.tabs.select(root.opencode)
            root.opencode.conversations.selection_set('0')
            self.wait_for(root, old_session_started.is_set)
            # Editing the source field alone must keep the loaded database pinned.
            root.opencode.db_path.set(str(source.with_name('missing.db')))
            root.opencode.conversations.selection_set('1')
            root.update()
            release_old_session.set()
            self.wait_for(root, lambda: root.opencode.result is not None)
            self.assertEqual(root.opencode.result['thread']['id'], 'other')
            self.assertEqual(len(root.opencode.cache), 1)
            self.assertTrue(root.codex._working)
            self.assertIsNone(root.codex.result)
            self.assertNotIn('Stale', root.opencode.status.get())
            ids = {agent: {ident for source_agent, _, ident in calls if source_agent == agent}
                   for agent in ('codex', 'opencode')}
            self.assertEqual([len(worker_ids) for worker_ids in ids.values()], [1, 1])
            self.assertTrue(ids['codex'].isdisjoint(ids['opencode']))
            self.assertNotIn(threading.get_ident(), ids['codex'] | ids['opencode'])
            release_codex.set()
            self.wait_for(root, lambda: root.codex.result is not None)
            codex_result = root.codex.result
            old_result = root.opencode.result
            root.opencode.conversations.selection_set('0')
            self.wait_for(root, lambda: root.opencode.result is not old_result and root.opencode.result)
            self.assertEqual(root.opencode.result['thread']['id'], 'session')
            self.assertIs(root.codex.result, codex_result)
            root.opencode.conversations.selection_set('1')
            self.wait_for(root, lambda: root.opencode.result is old_result)
            root.opencode._load()
            self.wait_for(root, lambda: not root.opencode._working)
            self.assertIn('Error reading OpenCode', root.opencode.status.get())
            self.assertIs(root.codex.result, codex_result)
            self.assertEqual(len(root.codex.cache), 1)

    def test_long_execution_output_is_rendered_once_and_scrolls_in_full(self):
        root = self.app()
        pane = root.opencode
        root.tabs.select(pane)
        output = ''.join(f'Output line {number} · café\n' for number in range(400)) + 'Unique ending'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'opencode.db'
            build_database(source, output=output)
            pane.db_path.set(str(source))
            pane._load()
            self.wait_for(root, lambda: not pane._working)
            with patch.object(pane, '_render_entry', wraps=pane._render_entry) as render:
                pane.conversations.selection_set('0')
                self.wait_for(root, lambda: pane.result is not None and pane._render_timer is None)

        rendered = [call.args[0] for call in render.call_args_list]
        rendered_types = {entry['part_type'] for entry in rendered}
        self.assertTrue({'step-start', 'reasoning', 'step-finish'}.isdisjoint(rendered_types))
        self.assertTrue({'user_prompt', 'assistant_response', 'execution', 'file_change', 'file_attachment'}
                        .issubset(entry['event_type'] for entry in rendered))
        self.assertNotIn('render warnings', pane.status.get())

        def descendants(parent):
            for child in parent.winfo_children():
                yield child
                yield from descendants(child)

        labels = [widget.cget('text') for widget in descendants(pane.canvas)
                  if isinstance(widget, tk.Label)]
        self.assertFalse(any(label.startswith(('Message ID', 'Part ID', 'Call ID')) for label in labels))
        call_ids = {entry['call_id'] for entry in rendered if 'execution' in entry and entry['call_id']}
        self.assertEqual(call_ids, {'bash-call', 'read-call'})
        self.assertFalse(any(call_id in label for call_id in call_ids for label in labels))
        self.assertEqual(labels.count('AGENT ERROR'), 1)
        self.assertNotIn('MESSAGE EVIDENCE', labels)
        error_entry, = (entry for entry in rendered if entry['event_type'] == 'assistant_error')
        error_card = pane._row_cache[id(error_entry)][1]
        self.assertEqual([widget.get('1.0', 'end-1c') for widget in descendants(error_card)
                          if isinstance(widget, tk.Text)], ['This API key has expired.'])

        body, = (widget for widget in descendants(pane.canvas) if isinstance(widget, tk.Text)
                 and widget.get('end-1c linestart', 'end-1c') == 'Unique ending')
        self.assertEqual(body.get('1.0', 'end-1c'), output)
        self.assertEqual(int(body['height']), 9)
        self.assertTrue(any(child.winfo_manager() == 'pack' for child in body.master.winfo_children()
                            if str(child.winfo_class()) == 'TScrollbar'))
        outer = pane.canvas.yview()
        body.event_generate('<MouseWheel>', delta=-120)
        self.assertGreater(body.yview()[0], 0)
        self.assertEqual(pane.canvas.yview(), outer)
        body.yview_moveto(1)
        body.event_generate('<MouseWheel>', delta=-120)
        self.assertGreater(pane.canvas.yview()[0], outer[0])
        pane.entry_type.set('Tool calls')
        pane.query.set('unique ending')
        self.wait_for(root, lambda: pane._search_timer is None and pane._render_timer is None)
        self.assertIn('1 matching entries', pane.status.get())
