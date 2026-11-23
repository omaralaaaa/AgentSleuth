import json
import sqlite3
import tempfile
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path

from agentsleuth.parsers import antigravity as provider
from agentsleuth.ui.app import App


class AntigravityTests(unittest.TestCase):
    def _reconstruct(self, records):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / 'transcript.jsonl'
            transcript.write_text('\n'.join(map(json.dumps, records)), encoding='utf-8')
            before = transcript.read_bytes()
            result = provider.reconstruct_from_thread(transcript, provider.load_threads(transcript)[0])
            self.assertEqual(transcript.read_bytes(), before)
            return result

    def test_user_request_extracts_only_authored_text_and_keeps_evidence(self):
        text = '  Inspect the report.  \r\n\r\n\tExplain the summary.\r\n'
        step = dict(type='USER_INPUT', step_index=0, created_at='2026-08-15T07:36:05+03:00',
                    truncated_fields=['content'], source='recorded source', content=(
                        f'Internal preface\r\n<USER_REQUEST>\r\n{text}\r\n</USER_REQUEST>\r\n'
                        '<ADDITIONAL_METADATA>Internal timestamp</ADDITIONAL_METADATA>\n'
                        '<USER_SETTINGS_CHANGE>Model changed</USER_SETTINGS_CHANGE>\n'
                        '<INTERNAL_INSTRUCTION>Internal suffix</INTERNAL_INSTRUCTION>'
                    ))
        result = self._reconstruct([step])
        entry, = result['turns'][0]['entries']
        self.assertEqual(entry['role'], 'user')
        self.assertEqual(entry['text'], text)
        self.assertEqual(entry['step_index'], 0)
        self.assertEqual(entry['timestamp'], step['created_at'])
        self.assertEqual(entry['raw'], step)
        self.assertEqual(result['user_records'], [step])

    def test_structured_plain_multiple_and_malformed_requests(self):
        literal = '<ADDITIONAL_METADATA>part of an example</ADDITIONAL_METADATA>\n' \
                  '<USER_REQUEST>also part of the example</USER_REQUEST>'
        samples = [
            ({'content': {'userRequest': f'Explain this XML\n{literal}', 'timestamp': 'internal'}},
             f'Explain this XML\n{literal}'),
            ({'content': '  Plain prompt\n\n  indented line  '}, '  Plain prompt\n\n  indented line  '),
            ({'content': f'<USER_REQUEST>\n{literal}\n</USER_REQUEST>'}, literal),
            ({'content': '<ADDITIONAL_METADATA><USER_REQUEST>fake</USER_REQUEST></ADDITIONAL_METADATA>'
                         '<USER_REQUEST>First</USER_REQUEST><USER_REQUEST>Second</USER_REQUEST>'
                         '<USER_REQUEST>First</USER_REQUEST>'}, 'First\n\nSecond'),
            ({'content': '<USER_REQUEST\nRecover this\n<USER_SETTINGS_CHANGE>internal'}, 'Recover this'),
            ({'content': '<ADDITIONAL_METADATA>metadata only</ADDITIONAL_METADATA>\n'}, ''),
        ]
        steps = [dict(type='USER_INPUT', **data) for data, _ in samples]
        result = self._reconstruct(steps)
        texts = [''.join(entry['text'] for entry in turn['entries']) for turn in result['turns']]
        self.assertEqual(texts, [expected for _, expected in samples])
        self.assertEqual(result['user_records'], steps)

    def test_viewer_renders_prompt_without_recorded_step_or_wrapper_fields(self):
        records = [dict(type='USER_INPUT', step_index=0, truncated_fields=['content'],
                        content='<USER_REQUEST>\nFirst line\n\nSecond line\n</USER_REQUEST>\n'
                                '<ADDITIONAL_METADATA>Internal timestamp</ADDITIONAL_METADATA>\n'
                                '<USER_SETTINGS_CHANGE>Internal setting</USER_SETTINGS_CHANGE>'),
                   dict(type='PLANNER_RESPONSE', step_index=1, content='Planner response')]
        try:
            app = App()
        except tk.TclError as error:
            if 'display' in str(error):
                self.skipTest(str(error))
            raise
        self.addCleanup(app.destroy)
        app.geometry('1000x700+10000+10000')
        pane = app.antigravity
        app.tabs.select(pane)

        def wait_for(condition):
            deadline = time.monotonic() + 5
            while not condition() and time.monotonic() < deadline:
                app.update()
                time.sleep(.01)
            self.assertTrue(condition())

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        with tempfile.TemporaryDirectory() as tmp:
            transcript = Path(tmp) / 'transcript.jsonl'
            transcript.write_text('\n'.join(map(json.dumps, records)), encoding='utf-8')
            pane.db_path.set(str(transcript))
            pane._load()
            wait_for(lambda: not pane._working)
            pane.conversations.selection_set('0')
            wait_for(lambda: pane.result is not None and pane._render_timer is None)

        prompt, planner = pane.result['turns'][0]['entries']
        prompt_widgets = list(descendants(pane._row_cache[id(prompt)][1]))
        labels = [widget.cget('text') for widget in prompt_widgets if isinstance(widget, tk.Label)]
        self.assertIn('USER', labels)
        self.assertFalse(any(label.startswith(('Recorded step', 'Truncated in source')) for label in labels))
        self.assertEqual([widget.get('1.0', 'end-1c') for widget in prompt_widgets
                          if isinstance(widget, tk.Text)], ['First line\n\nSecond line'])
        self.assertTrue(any(widget.cget('text').startswith('Recorded step:')
                            for widget in descendants(pane._row_cache[id(planner)][1])
                            if isinstance(widget, tk.Label)))

    def test_index_transcript_and_metadata_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = root / 'conversation_summaries.db'
            with closing(sqlite3.connect(index)) as db, db:
                db.execute('CREATE TABLE conversation_summaries '
                           '(conversation_id, title, workspace_uris, last_modified_time)')
                db.executemany('INSERT INTO conversation_summaries VALUES (?, ?, ?, ?)',
                               [('session', 'Example', '["file:///workspace"]', 1),
                                ('../outside', 'Missing', '[]', 0)])
            thread, missing = provider.load_threads(index)
            self.assertEqual(thread['cwd'], 'file:///workspace')
            self.assertEqual(provider.reconstruct_from_thread(index, missing)['turns'], [])
            dbpath = root / 'conversations' / 'session.db'
            dbpath.parent.mkdir()
            with closing(sqlite3.connect(dbpath)) as db, db:
                db.execute('CREATE TABLE steps(idx, step_type, status)')
                db.execute('INSERT INTO steps VALUES (7, 5, 3)')
            metadata = provider.reconstruct_from_thread(index, thread)
            self.assertIn('metadata only', metadata['source_detail'])
            self.assertEqual(metadata['turns'][0]['entries'][0]['step_index'], 7)
            transcript = root / 'brain/session/.system_generated/logs/transcript.jsonl'
            transcript.parent.mkdir(parents=True)
            records = [dict(type='USER_INPUT', content='Inspect the log', step_index=1),
                       dict(type='PLANNER_RESPONSE', tool_calls=[dict(name='view_file', args={'path':'log'})]),
                       dict(type='VIEW_FILE', content='Recorded result', truncated_fields=['content']),
                       dict(type='PLANNER_RESPONSE', content='Done'), dict(type='USER_INPUT', content='Next')]
            transcript.write_text('\n'.join(map(json.dumps, records)) + '\n{broken', encoding='utf-8')
            for source in (index, dbpath, transcript):
                selected = provider.load_threads(source)[0]
                result = provider.reconstruct_from_thread(source, selected)
                self.assertEqual(result['source_path'], str(transcript))
                self.assertEqual(result['summary']['turns'], 2)
                self.assertEqual(result['summary']['tool_calls'], 1)
                first, second = result['turns']
                self.assertEqual(first['entries'][0]['role'], 'user')
                self.assertEqual(first['entries'][2]['truncated_fields'], ['content'])
                self.assertEqual(first['entries'][-1]['role'], 'assistant')
                self.assertEqual(second['entries'][-1]['activity_type'], 'UNREADABLE_RECORD')
