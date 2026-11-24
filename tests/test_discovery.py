import sqlite3
import tempfile
import threading
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path

from agentsleuth.core.discovery import scan
from agentsleuth.parsers.codex.paths import rollout_for_thread
from agentsleuth.ui.app import App
from agentsleuth.ui.discovery import CHECKED, UNCHECKED


class DiscoveryTests(unittest.TestCase):
    def _app(self):
        try:
            app = App()
        except tk.TclError as error:
            if 'display' in str(error):
                self.skipTest(str(error))
            raise
        self.addCleanup(app.destroy)
        app.geometry('900x620+10000+10000')
        return app

    def _wait_until(self, app, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            app.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def _click_checkbox(self, app, dialog, row):
        x, y, width, height = dialog.table.bbox(row, 'check')
        self._click_time = getattr(self, '_click_time', 0) + 1000
        dialog.table.event_generate('<Button-1>', x=x + width // 2, y=y + height // 2, time=self._click_time)
        app.update()

    def test_open_scanned_collection_source_in_matching_tab(self):
        app = self._app()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / 'C/Users/user/.gemini/antigravity/brain/s/.system_generated/logs/transcript.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text('{"type":"USER_INPUT","content":"Sample"}\n', encoding='utf-8')
            folder = path.parents[4]
            other = folder / 'brain/t/.system_generated/logs/transcript.jsonl'
            other.parent.mkdir(parents=True)
            other.write_text('{"type":"USER_INPUT","content":"Another"}\n', encoding='utf-8')
            app.open_scanner()
            dialog = app.scanner
            dialog.geometry('530x300+10000+10000')
            dialog.start(root)
            self._wait_until(app, lambda: dialog.job is None)
            self.assertEqual([hit.path for hit in dialog.findings], [folder])
            self.assertTrue(dialog.open_button.winfo_ismapped())
            self.assertLess(dialog.table.xview()[1], 1)
            self._click_checkbox(app, dialog, '0')
            dialog.open_button.invoke()
            self._wait_until(app, lambda: app.antigravity._loaded_db == folder)
            self.assertEqual(app.tabs.select(), str(app.antigravity))
            self.assertEqual(app.antigravity.threads[0]['_evidence_root'], root)
            self.assertEqual([t['id'] for t in app.antigravity.threads], ['s', 't'])
            app.antigravity.conversations.selection_set('1')
            app.antigravity._select_thread()
            self._wait_until(app, lambda: app.antigravity.result is not None)
            self.assertEqual(app.antigravity.result['turns'][0]['entries'][0]['text'], 'Another')

    def test_open_selected_sources_keeps_duplicate_agent_sources_in_separate_tabs(self):
        app = self._app()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            folders = [root / 'Users' / user / '.gemini/antigravity' for user in ('alice', 'bob')]
            for folder, prompt in zip(folders, ('First profile', 'Second profile')):
                transcript = folder / 'brain/session/.system_generated/logs/transcript.jsonl'
                transcript.parent.mkdir(parents=True)
                transcript.write_text(f'{{"type":"USER_INPUT","content":"{prompt}"}}\n', encoding='utf-8')
            missing = root / 'Users/carol/.gemini/antigravity-ide'
            missing.mkdir(parents=True)
            database = root / 'Users/alice/.local/share/opencode/opencode.db'
            database.parent.mkdir(parents=True)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript("CREATE TABLE session (id TEXT, title TEXT);"
                                         "INSERT INTO session VALUES ('session', 'OpenCode source');"
                                         "CREATE TABLE message (id TEXT, session_id TEXT);"
                                         "CREATE TABLE part (id TEXT, message_id TEXT);")

            app.open_scanner()
            dialog = app.scanner
            self.assertIn('disabled', dialog.select_all_button.state())
            dialog.start(root)
            self._wait_until(app, lambda: dialog.job is None)
            missing_row, = (str(index) for index, hit in enumerate(dialog.findings) if hit.path == missing)
            app.update()
            results = dialog.table.get_children()
            self.assertEqual(len(results), len(dialog.findings))
            rows = [row for row in results if row != missing_row]
            self.assertEqual(dialog.table.selection(), ())
            select_all = dialog.select_all_button
            self.assertLess(select_all.winfo_x(), dialog.open_button.winfo_x())
            self.assertNotIn('disabled', select_all.state())
            self.assertEqual(str(select_all.cget('text')), 'Select all')
            self.assertEqual([dialog.table.set(row, 'check') for row in rows], [UNCHECKED] * len(rows))
            self.assertEqual(dialog.table.set(missing_row, 'check'), '')
            self._click_checkbox(app, dialog, missing_row)
            self.assertIn('disabled', dialog.open_button.state())
            self._click_checkbox(app, dialog, rows[0])
            self._click_checkbox(app, dialog, rows[1])
            self.assertEqual(set(dialog.table.selection()), set(rows[:2]))
            self.assertEqual(str(select_all.cget('text')), 'Select all')
            self._click_checkbox(app, dialog, rows[0])
            self.assertEqual(dialog.table.set(rows[0], 'check'), UNCHECKED)
            select_all.invoke()
            self.assertEqual(set(dialog.table.selection()), set(rows))
            self.assertEqual([dialog.table.set(row, 'check') for row in rows], [CHECKED] * len(rows))
            self.assertEqual(str(select_all.cget('text')), 'Clear selection')
            select_all.invoke()
            self.assertEqual(dialog.table.selection(), ())
            self.assertEqual(str(select_all.cget('text')), 'Select all')
            self.assertIn('disabled', dialog.open_button.state())
            select_all.invoke()
            dialog.open_button.invoke()
            panes = {Path(pane.db_path.get()): pane for pane in app._agent_panes if pane.db_path.get()}
            self.assertEqual(set(panes), {*folders, database})
            self._wait_until(app, lambda: all(pane._loaded_db == source for source, pane in panes.items()))
            self.assertIs(panes[folders[0]], app.antigravity)
            second = panes[folders[1]]
            self.assertIsNot(second.worker, app.antigravity.worker)
            self.assertIs(second.output_root, app.output_root)
            self.assertIs(panes[database], app.opencode)
            self.assertEqual(app.opencode.threads[0]['name'], 'OpenCode source')
            for source in folders:
                pane = panes[source]
                self.assertEqual(pane.threads[0]['_evidence_root'], root)
                self.assertIsNone(pane.result)
                pane.conversations.selection_set('0')
                pane._select_thread()
            self._wait_until(app, lambda: all(panes[source].result is not None for source in folders))
            self.assertEqual([panes[source].result['turns'][0]['entries'][0]['text'] for source in folders],
                             ['First profile', 'Second profile'])

            app.open_scanner()
            reopened = app.scanner
            reopened.start(root)
            self._wait_until(app, lambda: reopened.job is None)
            reopened._select_all()
            requests = {pane: pane.worker.request for pane in panes.values()}
            reopened.open_button.invoke()
            self.assertEqual(len(app.tabs.tabs()), 5)
            self.assertEqual({pane: pane.worker.request for pane in panes.values()}, requests)
            app.close_source_tab(second)
            self.assertNotIn(str(second), app.tabs.tabs())
            self.assertNotIn(second, app._agent_panes)

    def test_collection_preserves_profiles_and_distinguishes_companions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / 'Acquisition' / 'C' / 'Users' / 'alice'
            paths = [
                profile / '.codex/state_5.sqlite',
                profile.parent / 'bob/.codex/state_5.sqlite',
                profile / '.codex/sessions/2026/rollout-example.jsonl',
                profile / '.claude/history.jsonl',
                profile / '.claude/projects/example/session.jsonl',
                profile / '.local/share/opencode/opencode.db',
                profile / '.gemini/antigravity/conversation_summaries.db',
                profile / '.gemini/antigravity/brain/id/.system_generated/logs/transcript.jsonl',
                profile / '.gemini/antigravity-ide/conversations/old.pb',
                profile / 'unrelated/history.jsonl',
                profile / '.codex/state_5.sqlite-wal',
            ]
            for p in paths:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.touch()
            hits, skipped = scan([root], threading.Event(), lambda *_: None)
            self.assertEqual(skipped, 0)
            self.assertEqual({h.path for h in hits}, {paths[i].parent for i in (0, 1, 3, 5, 6)}
                             | {profile / '.gemini/antigravity-ide'})
            self.assertEqual({h.source for h in hits if h.source and h.source.is_file()},
                             {paths[i] for i in (0, 1, 3, 5, 6)})
            stop = threading.Event()
            stop.set()
            self.assertEqual(scan([root], stop, lambda *_: None)[0], [])

    def test_offline_rollout_never_falls_back_to_existing_live_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root / 'live/sessions/test.jsonl'
            live.parent.mkdir(parents=True)
            live.touch()
            collection = root / 'capture'
            db = collection / 'Users/u/.codex/state_5.sqlite'
            db.parent.mkdir(parents=True)
            thread = {'rollout_path': str(live), '_evidence_root': collection}
            with self.assertRaises(FileNotFoundError):
                rollout_for_thread(db, thread)
            captured = db.parent / 'sessions/test.jsonl'
            captured.parent.mkdir()
            captured.touch()
            self.assertEqual(rollout_for_thread(db, thread), captured)
