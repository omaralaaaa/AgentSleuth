import sqlite3
import tempfile
import time
import tkinter as tk
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from agentsleuth.core.artifacts import ArtifactStore, write_artifact
from agentsleuth.core.export import ExportSession, SESSION_OWNER, owns_session_directory
from agentsleuth.parsers import antigravity, claude, codex, opencode
from agentsleuth.parsers.claude.artifacts import Artifacts
from agentsleuth.parsers.claude.recovery import operation
from agentsleuth.parsers.codex.attachments import AttachmentExtractor
from agentsleuth.parsers.codex.recovery import _recover_file_changes
from agentsleuth.parsers.opencode.attachments import parse_upload
from agentsleuth.ui.app import App


AGENTS = {'Codex', 'OpenCode', 'Claude', 'Antigravity'}


class ExportDirectoryTests(unittest.TestCase):
    def test_parsing_without_artifacts_creates_no_export_directories_for_all_agents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / 'exports'
            rollout = root / 'rollout.jsonl'
            rollout.touch()
            codex_db = root / 'state_5.sqlite'
            codex_db.touch()
            codex_thread = {'id': 'session', 'name': 'Codex title', 'rollout_path': rollout.name}
            opencode_db = root / 'opencode.db'
            with closing(sqlite3.connect(opencode_db)) as db, db:
                db.executescript("CREATE TABLE session (id TEXT, title TEXT); "
                                 "INSERT INTO session VALUES ('session', 'OpenCode title');"
                                 'CREATE TABLE message (id TEXT, session_id TEXT);'
                                 'CREATE TABLE part (id TEXT, message_id TEXT);')
            history = root / '.claude' / 'history.jsonl'
            transcript = history.parent / 'projects' / 'fixture' / 'session.jsonl'
            transcript.parent.mkdir(parents=True)
            history.write_text('{"sessionId":"session","display":"Hello"}\n', encoding='utf-8')
            transcript.write_text('{"type":"user","sessionId":"session",'
                                  '"message":{"role":"user","content":"Hello"}}\n', encoding='utf-8')
            antigravity_source = root / 'brain' / 'session' / antigravity.parser.TRANSCRIPT
            antigravity_source.parent.mkdir(parents=True)
            antigravity_source.write_text('{"type":"USER_INPUT","content":"Hello"}\n', encoding='utf-8')
            antigravity_index = root / 'conversation_summaries.db'
            with closing(sqlite3.connect(antigravity_index)) as db, db:
                db.executescript("CREATE TABLE conversation_summaries "
                                 "(conversation_id, title, workspace_uris, last_modified_time);"
                                 "INSERT INTO conversation_summaries VALUES ('session', 'Antigravity title', '[]', 0);")
            sources = [
                ('Codex', codex, codex_db, codex_thread),
                ('OpenCode', opencode, opencode_db, opencode.load_threads(opencode_db)[0]),
                ('Claude', claude, history, claude.load_threads(history)[0]),
                ('Antigravity', antigravity, antigravity_index, antigravity.load_threads(antigravity_index)[0]),
            ]
            for agent, parser, path, thread in sources:
                with self.subTest(agent=agent):
                    result = parser.reconstruct_from_thread(path, thread, output)
                    session = Path(result['output_directory'])
                    self.assertEqual(session, output / agent / thread['name'])
                    self.assertEqual(result['thread']['id'], 'session')
                    self.assertFalse(output.exists())

    def test_exports_create_only_the_required_artifact_category(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / 'custom' / 'exports'
            codex_export = ExportSession(output, 'Codex', 'session', 'Review Windows injection code')
            extractor = AttachmentExtractor(codex_export)
            record = {'type': 'response_item', 'ordinal': 1}
            extractor.sanitize('data:image/png;base64,not-base64!', record)
            self.assertFalse(output.exists())
            extractor.sanitize('data:image/png;base64,aGVsbG8=', record)
            codex_dir = codex_export.directory
            self.assertEqual(codex_dir.name, 'Review Windows injection code')
            self.assertEqual((codex_dir / 'attachments' / extractor.entries[0]['filename']).read_bytes(), b'hello')
            self.assertFalse((codex_dir / 'recovered_files').exists())

            changes = [{'activity_type': 'FileChange', 'ordinal': 1, 'item': {'changes': {
                'hello.txt': {'type': 'create', 'content': 'hello'},
            }}}]
            second_codex_export = ExportSession(output, 'Codex', 'recovery-session', 'Review notes')
            with patch('agentsleuth.parsers.codex.recovery.MAX_ATTACHMENT_BYTES', 1):
                self.assertEqual(_recover_file_changes(changes, second_codex_export), [])
            self.assertFalse(second_codex_export.directory.exists())
            recovered, = _recover_file_changes(changes, second_codex_export)
            self.assertEqual(Path(recovered['saved_path']).read_bytes(), b'hello')
            self.assertEqual({path.name for path in second_codex_export.directory.iterdir() if path.is_dir()},
                             {'recovered_files'})

            claude_store = Artifacts(output, root / 'claude-evidence', 'session', (), title='Claude title')
            recovered = operation({'tool': 'Write', 'status': 'completed', 'arguments': {
                'file_path': 'hello.txt', 'content': 'hello',
            }}, {}, claude_store)
            self.assertEqual(Path(recovered['saved_path']).read_bytes(), b'hello')
            self.assertEqual({path.name for path in claude_store.directory.iterdir() if path.is_dir()}, {'recovered_files'})

            opencode_store = ArtifactStore(ExportSession(output, 'OpenCode', 'session', 'OpenCode title'))
            attachment = parse_upload({'filename': 'copy.txt', 'url': 'data:text/plain,hello%20world'}, opencode_store)
            self.assertEqual(Path(attachment['saved_path']).read_bytes(), b'hello world')
            self.assertEqual({path.name for path in opencode_store.directory.iterdir() if path.is_dir()}, {'attachments'})
            self.assertFalse((output / 'Antigravity').exists())

    def test_failed_write_rolls_back_only_its_own_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'exports'
            original_open = Path.open

            class InterruptedWrite:
                def __init__(self, stream):
                    self.stream = stream

                def __enter__(self):
                    return self

                def __exit__(self, *_):
                    self.stream.close()

                def fileno(self):
                    return self.stream.fileno()

                def write(self, blob):
                    self.stream.write(blob[:2])
                    raise OSError('simulated failure after a partial write')

            def interrupted_open(path, mode, *args, **kwargs):
                stream = original_open(path, mode, *args, **kwargs)
                return InterruptedWrite(stream) if mode == 'xb' else stream

            with patch.object(Path, 'open', interrupted_open):
                for agent in sorted(AGENTS):
                    with self.subTest(agent=agent):
                        store = ArtifactStore(ExportSession(root, agent, 'session', 'Export title'))
                        with self.assertRaisesRegex(OSError, 'simulated failure'):
                            store.save('attachments', 'example.txt', b'hello')
                        self.assertFalse(root.exists())

            def interrupt_marker(path, mode, *args, **kwargs):
                if mode == 'xb' and path.name == SESSION_OWNER:
                    return interrupted_open(path, mode, *args, **kwargs)
                return original_open(path, mode, *args, **kwargs)

            with patch.object(Path, 'open', interrupt_marker):
                store = ArtifactStore(ExportSession(root, 'Codex', 'session', 'Export title'))
                with self.assertRaisesRegex(OSError, 'simulated failure'):
                    store.save('attachments', 'example.txt', b'hello')
                self.assertFalse(root.exists())

            existing = root / 'Codex' / 'session' / 'attachments' / 'existing.txt'
            write_artifact(existing, b'original')
            user_directory = root / 'Codex' / 'user-created' / 'recovered_files'
            user_directory.mkdir(parents=True)
            with patch.object(Path, 'open', interrupted_open):
                for parent in (existing.parent.parent / 'recovered_files', user_directory):
                    with self.assertRaisesRegex(OSError, 'simulated failure'):
                        write_artifact(parent / 'test.txt', b'new data')
            self.assertFalse((existing.parent.parent / 'recovered_files').exists())
            self.assertTrue(user_directory.is_dir())
            self.assertEqual(list(user_directory.iterdir()), [])
            with self.assertRaisesRegex(ValueError, 'different evidence'):
                write_artifact(existing, b'replacement')
            self.assertEqual(existing.read_bytes(), b'original')
            self.assertEqual(list(existing.parent.iterdir()), [existing])

    def test_export_titles_sanitize_unsafe_names_and_handle_missing_titles(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'exports'
            for title, expected in [(None, 'Unnamed_Conversation'), (' .  ', 'Unnamed_Conversation'),
                                    ('CON.md', '_CON.md'), ('A/B:C\\D?* ', 'A_B_C_D__')]:
                with self.subTest(title=title):
                    directory = ExportSession(root, 'Codex', '../escape', title).directory
                    self.assertEqual(directory, root / 'Codex' / expected)
            self.assertLessEqual(len(ExportSession(root, 'Codex', 'session', '漢' * 100).directory.name.encode()), 120)
            self.assertFalse(root.exists())

    def test_title_collisions_use_short_session_suffix_and_preserve_existing_exports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'exports'
            for agent in sorted(AGENTS):
                with self.subTest(agent=agent):
                    first = ArtifactStore(ExportSession(root, agent, 'abcdefgh-first', 'Review code'))
                    second = ArtifactStore(ExportSession(root, agent, 'abcdefgh-second', 'Review code'))
                    third = ArtifactStore(ExportSession(root, agent, 'abcdefgh-third', 'Review code'))
                    self.assertEqual(first.directory, second.directory)
                    paths = [Path(store.save('attachments', 'test.txt', blob)['saved_path'])
                             for store, blob in zip((first, second, third), (b'1', b'2', b'3'))]
                    self.assertEqual([path.parent.parent.name for path in paths],
                                     ['Review code', 'Review code (abcdefgh)', 'Review code (abcdefgh-2)'])
                    for store, suffix in zip((first, second, third), ('first', 'second', 'third')):
                        self.assertTrue(owns_session_directory(store.directory, f'abcdefgh-{suffix}'))
                    reopened = ArtifactStore(ExportSession(root, agent, 'abcdefgh-second', 'Review code'))
                    self.assertEqual(Path(reopened.save('attachments', 'test.txt', b'2')['saved_path']), paths[1])
                    self.assertEqual([path.read_bytes() for path in paths], [b'1', b'2', b'3'])

                    legacy = root / agent / 'Legacy title' / 'recovered_files' / 'existing.txt'
                    write_artifact(legacy, b'legacy')
                    store = ArtifactStore(ExportSession(root, agent, 'new-session', 'legacy title'))
                    store.save('attachments', 'test.txt', b'new')
                    self.assertEqual(store.directory.name, 'legacy title (new-sess)')
                    self.assertEqual(legacy.read_bytes(), b'legacy')
                    self.assertFalse((legacy.parent.parent / SESSION_OWNER).exists())

    def test_default_is_beside_launcher_and_custom_choice_survives_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            launcher = root / 'app'
            preference = root / 'profile' / 'export.json'
            default = launcher / 'AgentSleuth_Export'
            custom = root / 'custom' / 'exports'
            evidence = root / 'evidence'
            for session_id in ('session', 'session-two'):
                transcript = evidence / 'brain' / session_id / antigravity.parser.TRANSCRIPT
                transcript.parent.mkdir(parents=True)
                transcript.write_text('{"type":"USER_INPUT","content":"Hello"}\n', encoding='utf-8')
            with patch('agentsleuth.ui.app.preference_path', return_value=preference):
                try:
                    app = App(script_directory=launcher)
                except tk.TclError as error:
                    if 'display' in str(error):
                        self.skipTest(str(error))
                    raise
                try:
                    app.geometry('1000x700+10000+10000')
                    self.assertEqual(Path(app.output_root.get()), default)
                    self.assertFalse(default.exists())
                    self.assertFalse(preference.exists())

                    def wait_for(condition):
                        deadline = time.monotonic() + 5
                        while not condition() and time.monotonic() < deadline:
                            app.update()
                            time.sleep(.01)
                        self.assertTrue(condition())

                    pane = app.antigravity
                    app.tabs.select(pane)
                    pane.db_path.set(str(evidence))
                    pane._load()
                    wait_for(lambda: pane._loaded_db == evidence)
                    self.assertFalse(default.exists())
                    pane.conversations.selection_set('0')
                    wait_for(lambda: pane.result is not None)
                    self.assertEqual(Path(pane.result['output_directory']), default / 'Antigravity' / 'Unnamed_Conversation')
                    self.assertFalse(default.exists())
                    with patch('agentsleuth.ui.controller.filedialog.askdirectory', return_value=str(custom)):
                        app.codex._browse_output()
                    wait_for(lambda: pane.result is not None and
                             Path(pane.result['output_directory']) == custom / 'Antigravity' / 'Unnamed_Conversation')
                    pane.conversations.selection_set('1')
                    wait_for(lambda: pane.result is not None and pane.result['thread']['id'] == 'session-two')
                    self.assertEqual(Path(pane.result['output_directory']), custom / 'Antigravity' / 'Unnamed_Conversation')
                    self.assertFalse(custom.exists())
                    self.assertTrue(all(Path(pane.output_root.get()) == custom for pane in app._agent_panes))
                    with patch('agentsleuth.ui.controller.filedialog.askdirectory', return_value=''):
                        pane._browse_output()
                    self.assertEqual(Path(app.output_root.get()), custom)
                finally:
                    app.destroy()

                moved_launcher = root / 'another-app'
                app = App(script_directory=moved_launcher)
                try:
                    self.assertEqual(Path(app.output_root.get()), custom)
                    self.assertFalse(custom.exists())
                    self.assertFalse((moved_launcher / 'AgentSleuth_Export').exists())
                finally:
                    app.destroy()
