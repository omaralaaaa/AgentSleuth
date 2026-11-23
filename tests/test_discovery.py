import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path

from agentsleuth.core.discovery import scan
from agentsleuth.parsers.codex.paths import rollout_for_thread
from agentsleuth.ui.app import App


class DiscoveryTests(unittest.TestCase):
    def test_open_scanned_collection_source_in_matching_tab(self):
        try:
            app = App()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(app.destroy)
        app.geometry('900x620+10000+10000')
        def wait_until(predicate):
            deadline = time.monotonic() + 5
            while not predicate() and time.monotonic() < deadline:
                app.update()
                time.sleep(.01)
            self.assertTrue(predicate())
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
            wait_until(lambda: dialog.job is None)
            self.assertEqual([hit.path for hit in dialog.findings], [folder])
            self.assertTrue(dialog.open_button.winfo_ismapped())
            self.assertLess(dialog.table.xview()[1], 1)
            dialog.open_button.invoke()
            wait_until(lambda: app.antigravity._loaded_db == folder)
            self.assertEqual(app.tabs.select(), str(app.antigravity))
            self.assertEqual(app.antigravity.threads[0]['_evidence_root'], root)
            self.assertEqual([t['id'] for t in app.antigravity.threads], ['s', 't'])
            app.antigravity.conversations.selection_set('1')
            app.antigravity._select_thread()
            wait_until(lambda: app.antigravity.result is not None)
            self.assertEqual(app.antigravity.result['turns'][0]['entries'][0]['text'], 'Another')

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
