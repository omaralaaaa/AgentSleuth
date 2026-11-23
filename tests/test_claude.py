import base64
import json
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from agentsleuth.parsers import claude
from agentsleuth.parsers.claude import history as history_reader
from agentsleuth.parsers.claude.paths import project_component
from agentsleuth.ui.app import App


SESSION = 'c4ea9a96-ff1a-412d-af20-7b966ed01f9f'
PROJECT = r'D:\CD'
IMAGE = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a'
         'PeQAAAAASUVORK5CYII=')


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(json.dumps(row) if isinstance(row, dict) else row for row in rows) + '\n',
                    encoding='utf-8')


def message(role, uid, content, *, parent=None, model_id=None, time='2026-01-01T00:00:01Z', **fields):
    return {'type': role, 'uuid': uid, 'sessionId': SESSION, 'timestamp': time,
            'parentUuid': parent, 'cwd': PROJECT, 'message': {'role': role, 'id': model_id, 'content': content},
            **fields}


def tool(call_id, name, **arguments):
    return {'type': 'tool_use', 'id': call_id, 'name': name, 'input': arguments}


def returned(call_id, content, **fields):
    return {'type': 'tool_result', 'tool_use_id': call_id, 'content': content, **fields}


def build_fixture(root, output='bash recorded output'):
    evidence = root / '.claude'
    index = evidence / 'history.jsonl'
    transcript = evidence / 'projects' / 'D--CD' / f'{SESSION}.jsonl'
    write_jsonl(index, [
        {'sessionId': SESSION, 'display': 'Later prompt', 'project': PROJECT, 'timestamp': 1800},
        {'sessionId': SESSION, 'display': '/model', 'project': PROJECT, 'timestamp': 1200},
        '[malformed',
        {'sessionId': 'missing-session', 'display': '/permissions', 'project': '/home/user/test', 'timestamp': 1000},
        {'sessionId': SESSION, 'display': 'Create hello.txt', 'project': PROJECT, 'timestamp': 1500,
         'pastedContents': {'1': {'type': 'image'}}},
        {'sessionId': '../outside', 'display': 'Unsafe identifier', 'project': PROJECT, 'timestamp': 900},
    ])
    file_path = r'D:\CD\hello.txt'
    write_jsonl(transcript, [
        message('user', 'internal', '<local-command-stdout>private CLI output</local-command-stdout>'),
        message('user', 'metaprompt', 'hidden metadata', isMeta=True),
        message('user', 'slash', '/model'),
        message('user', 'user-one', [{'type': 'text', 'text': 'Create hello.txt [Image #1]'},
                                     {'type': 'image', 'source': {'type': 'base64', 'data': IMAGE,
                                                                  'media_type': 'image/png'}}],
                time='2026-01-01T00:00:09Z', permissionMode='default'),
        message('assistant', 'thought', [{'type': 'thinking', 'thinking': 'reasoning evidence'}],
                parent='user-one', model_id='model-one'),
        '{broken JSON',
        message('assistant', 'call', [tool('call-write', 'Write', file_path=file_path, content='Hello, World!'),
                                      tool('call-bash', 'Bash', command='example-command')],
                parent='thought', model_id='model-one', requestId='request-1'),
        message('user', 'results', [returned('call-bash', output), returned('call-write', 'File created')],
                parent='call', sourceToolAssistantUUID='call', time='2026-01-01T00:00:03Z'),
        message('assistant', 'reply', [{'type': 'text', 'text': 'I created hello.txt.'}],
                parent='results', model_id='model-one'),
        message('assistant', 'replay', [{'type': 'text', 'text': 'I created hello.txt.'}],
                parent='reply', model_id='model-one'),
        message('assistant', 'continued', [{'type': 'text', 'text': 'Anything else?'}],
                parent='reply', model_id='model-one'),
        message('user', 'side-root', 'Sidechain prompt', parent='user-one', isSidechain=True),
        message('assistant', 'side-child', 'Sidechain response', parent='side-root'),
        {'type': 'file-history-snapshot', 'messageId': 'user-one', 'snapshot': {'trackedFileBackups': {
            r'D:\CD\previous.txt': {'backupFileName': 'backup@v1', 'version': 1},
            r'D:\CD\missing.txt': {'backupFileName': 'missing@v1'},
            r'D:\CD\outside.txt': {'backupFileName': '../../history.jsonl'},
        }}},
        message('user', 'user-two', 'Second real prompt', parent='continued'),
        message('assistant', 'second-call', [
            tool('call-edit', 'Edit', file_path=file_path, old_string='World', new_string='Claude'),
            tool('call-partial', 'Edit', file_path=r'D:\CD\partial.txt', old_string='a', new_string='b'),
            tool('call-missing', 'Write', file_path=r'..\..\proposed.txt', content='unverified bytes'),
            tool('call-failed', 'Read', file_path=r'D:\CD\denied.txt'),
            tool('call-dynamic', 'CustomTool', option=True),
        ], parent='user-two', model_id='model-two'),
        message('user', 'edited', [returned('call-edit', 'Edited')], parent='second-call',
                toolUseResult={'filePath': file_path, 'type': 'update', 'originalFile': 'Hello, World!',
                               'structuredPatch': [{'oldStart': 1, 'newStart': 1}]}),
        message('user', 'partial', [returned('call-partial', 'Partial patch')], parent='second-call',
                toolUseResult={'structuredPatch': [{'oldStart': 2, 'newStart': 2}]}),
        message('user', 'failed', [returned('call-failed', 'Permission denied', is_error=True)],
                parent='second-call'),
        message('user', 'dynamic', [returned('call-dynamic', 'Custom result')], parent='second-call'),
        message('assistant', 'api-error', [{'type': 'text', 'text': 'Service unavailable.'}],
                isApiErrorMessage=True, error='unavailable'),
        {'type': 'unknown-record', 'retain': True},
    ])
    backup = evidence / 'file-history' / SESSION / 'backup@v1'
    backup.parent.mkdir(parents=True)
    backup.write_bytes(b'snapshot bytes')
    subagent = transcript.parent / SESSION / 'subagents' / 'agent-example.jsonl'
    write_jsonl(subagent, [message('assistant', 'agent-one', 'Separate subagent response')])
    return index, transcript, root / 'results'


def entries_for(result):
    return [entry for turn in result['turns'] for entry in turn['entries']]


class ClaudeParserTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.index, self.transcript, self.output = build_fixture(self.root)

    def parse(self, root=None):
        thread = claude.load_threads(self.index)[0]
        return claude.reconstruct_from_thread(self.index, thread, root or self.output)

    def test_history_groups_titles_and_resolves_filenames_without_reading_transcripts(self):
        with patch.object(history_reader, 'records', wraps=history_reader.records) as reader:
            current, missing = claude.load_threads(self.index)
        reader.assert_called_once_with(self.index)
        self.assertEqual((current['id'], current['name'], current['cwd']), (SESSION, 'Create hello.txt', PROJECT))
        self.assertEqual((current['time_created'], current['time_updated']), (1200, 1800))
        self.assertEqual([ref['line_number'] for ref in current['history']], [1, 2, 5])
        self.assertEqual(current['history'][-1]['raw']['pastedContents'], {'1': {'type': 'image'}})
        self.assertEqual(Path(current['transcript_path']), self.transcript)
        self.assertEqual(project_component(PROJECT), 'D--CD')
        self.assertEqual(project_component('/home/user/my work'), '-home-user-my-work')
        self.assertEqual(missing['name'], 'Untitled Claude Session')
        self.assertIsNone(missing['transcript_path'])
        with self.assertRaisesRegex(FileNotFoundError, 'transcript is missing'):
            claude.reconstruct_from_thread(self.index, missing, self.output)

    def test_resolver_finds_moved_exact_transcript_and_reports_ambiguity_and_mismatches(self):
        projects = self.transcript.parent.parent
        moved = projects / 'unexpected-folder' / self.transcript.name
        moved.parent.mkdir()
        self.transcript.rename(moved)
        self.assertEqual(Path(self.parse()['source_path']), moved)
        alternate = projects / 'other-folder' / self.transcript.name
        write_jsonl(alternate, [])
        with self.assertRaisesRegex(ValueError, 'Multiple Claude Code transcripts'):
            self.parse()
        write_jsonl(self.transcript, [message('user', 'wrong', 'Unrelated', sessionId='foreign')])
        with self.assertRaisesRegex(ValueError, 'session ID mismatch at line 1'):
            self.parse()

    def test_order_turns_source_records_and_separate_sidechains(self):
        result = self.parse()
        main = entries_for(result)
        self.assertEqual([entry['text'] for entry in main if entry['kind'] == 'message'], [
            'Create hello.txt [Image #1]', 'I created hello.txt.', 'Anything else?',
            'Second real prompt', 'Service unavailable.',
        ])
        self.assertEqual([turn['turn_id'] for turn in result['turns']], ['user-one', 'user-two'])
        self.assertEqual([entry['event_type'] for entry in result['turns'][0]['entries']],
                         ['user_prompt', 'execution', 'execution', 'assistant_response', 'assistant_response'])
        self.assertEqual([entry['line_number'] for entry in main], sorted(entry['line_number'] for entry in main))
        self.assertEqual(result['summary']['invalid_json'], 1)
        self.assertEqual(result['records'][4]['raw']['message']['content'][0]['type'], 'thinking')
        self.assertGreater(result['records'][4]['byte_offset'], 0)
        self.assertEqual(result['records'][-1]['raw']['type'], 'unknown-record')
        self.assertEqual(main[0]['raw']['source']['raw']['permissionMode'], 'default')
        self.assertEqual([[entry['text'] for entry in entries_for(branch)] for branch in result['sidechains']],
                         [['Sidechain prompt', 'Sidechain response'], ['Separate subagent response']])

    def test_correlates_batch_results_and_keeps_missing_or_failed_states(self):
        main = {entry['call_id']: entry for entry in entries_for(self.parse()) if 'execution' in entry}
        write = main['call-write']
        self.assertEqual(write['execution']['output'], 'File created')
        self.assertEqual(write['execution']['status'], 'completed')
        self.assertEqual((write['execution']['start'], write['execution']['end']),
                         ('2026-01-01T00:00:01Z', '2026-01-01T00:00:03Z'))
        self.assertEqual(write['parent_uuid'], 'thought')
        self.assertEqual(write['raw']['tool_use']['id'], 'call-write')
        self.assertEqual(write['raw']['results'][0]['source']['raw']['uuid'], 'results')
        self.assertEqual(main['call-bash']['execution']['output'], 'bash recorded output')
        self.assertEqual(main['call-failed']['execution']['error'], 'Permission denied')
        self.assertEqual(main['call-failed']['execution']['status'], 'failed')
        self.assertEqual(main['call-missing']['execution']['status'], 'Result missing')
        self.assertIsNone(main['call-missing']['execution']['output'])
        self.assertEqual(main['call-dynamic']['execution']['tool'], 'CustomTool')

    def test_assistant_errors_render_readable_text_and_preserve_raw_evidence(self):
        payload = {'error': {'message': 'No allowed providers are available for the selected model.'},
                   'request_id': 'example-request', 'metadata': {'requested_providers': ['example']}}
        wrapped = 'API Error: 400 ' + json.dumps(payload)
        nested = message('assistant', 'structured', None, model_id='shared-error-model')
        nested['message']['error'] = {'data': {'message': 'The API key has expired.'}}
        detail = message('assistant', 'detail', None, model_id='shared-error-model',
                         error={'detail': 'The connection timed out.'})
        rows = [
            message('assistant', 'wrapped', [{'type': 'text', 'text': wrapped}],
                    isApiErrorMessage=True, error='invalid_request'),
            message('assistant', 'plain', 'Credit balance is too low', isApiErrorMessage=True),
            nested,
            detail,
            message('assistant', 'malformed', 'API Error: 500 {"metadata":',
                    error={'message': 'Provider unavailable.'}),
            message('assistant', 'empty', None, isApiErrorMessage=True),
            message('assistant', 'normal', wrapped),
        ]
        write_jsonl(self.transcript, rows)
        entries = entries_for(self.parse())
        self.assertEqual([(entry['event_type'], entry['text']) for entry in entries], [
            ('assistant_error', payload['error']['message']),
            ('assistant_error', 'Credit balance is too low'),
            ('assistant_error', 'The API key has expired.'),
            ('assistant_error', 'The connection timed out.'),
            ('assistant_error', 'Provider unavailable.'),
            ('assistant_error', 'No error message recorded.'),
            ('assistant_response', wrapped),
        ])
        self.assertEqual([entry['raw']['source']['raw'] for entry in entries], rows)

    def test_reused_tool_ids_use_recorded_source_relationships(self):
        shared_call = tool('reused', 'Read', file_path='sample.txt')
        write_jsonl(self.transcript, [
            message('assistant', 'first', [shared_call], model_id='model-first'),
            message('assistant', 'second', [shared_call], model_id='model-second'),
            message('user', 'recent-result', [returned('reused', 'Second result')],
                    sourceToolAssistantUUID='second'),
            message('user', 'older-result', [returned('reused', 'First result')], parent='first'),
        ])
        first, second = entries_for(self.parse())
        self.assertEqual((first['execution']['output'], second['execution']['output']),
                         ('First result', 'Second result'))

    def test_recovers_write_edit_attachment_and_snapshot_copies(self):
        original_history = self.index.read_bytes()
        original_transcript = self.transcript.read_bytes()
        result = self.parse()
        files = result['file_operations']
        prompts = [entry for entry in entries_for(result) if entry['event_type'] == 'user_prompt']
        self.assertEqual([[file['filename'] for file in entry['file_links']] for entry in prompts],
                         [['image.png'], []])
        saved = {item['operation']: item for item in files if item['saved_path']}
        write = next(item for item in files if item['operation'] == 'write' and item['status'] == 'completed')
        self.assertEqual(Path(write['saved_path']).read_bytes(), b'Hello, World!')
        self.assertEqual(Path(saved['edit']['saved_path']).read_bytes(), b'Hello, Claude!')
        self.assertEqual(Path(saved['snapshot']['saved_path']).read_bytes(), b'snapshot bytes')
        self.assertTrue(saved['snapshot']['backup_source'].endswith('backup@v1'))
        proposed = saved['write']
        self.assertIn('proposed', proposed['suffix'])
        self.assertEqual(Path(proposed['saved_path']).read_bytes(), b'unverified bytes')
        self.assertIsNone(next(item['saved_path'] for item in files if item['filename'] == 'partial.txt'))
        self.assertTrue(all(item['saved_path'] is None for item in files
                            if item['filename'] in ('missing.txt', 'outside.txt', 'denied.txt')))
        image, = result['attachments']
        self.assertEqual((image['mime'], image['source']['raw']['uuid']), ('image/png', 'user-one'))
        self.assertEqual(Path(image['saved_path']).read_bytes(), base64.b64decode(IMAGE))
        session_output = self.output / 'Claude' / result['thread']['name']
        self.assertEqual(Path(result['output_directory']), session_output)
        stored = list(session_output.glob('*/*'))
        self.assertEqual(len(stored), 5)
        self.parse()
        self.assertEqual(list(session_output.glob('*/*')), stored)
        self.assertEqual(self.index.read_bytes(), original_history)
        self.assertEqual(self.transcript.read_bytes(), original_transcript)

    def test_results_cannot_be_written_inside_evidence(self):
        result = self.parse(self.index.parent / 'results')
        self.assertTrue(result['file_operations'])
        self.assertFalse(result['recovered_files'])
        self.assertFalse((self.index.parent / 'results').exists())

    def test_uses_recorded_file_content_and_rejects_invalid_embedded_data(self):
        file_path = r'D:\CD\read.txt'
        image = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': IMAGE}}
        invalid = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'bad!'}}
        write_jsonl(self.transcript, [
            message('user', 'user', [image, image, invalid]),
            message('assistant', 'write', [tool('write', 'Write', file_path=file_path, content='proposed')]),
            message('user', 'write-done', [returned('write', 'Recorded create')],
                    toolUseResult={'type': 'create', 'filePath': file_path, 'content': 'recorded'}),
            message('assistant', 'read', [tool('read', 'Read', file_path=file_path)]),
            message('user', 'read-done', [returned('read', 'Recorded read')], toolUseResult={
                'type': 'text', 'file': {'filePath': file_path, 'startLine': 1,
                                         'numLines': 1, 'totalLines': 1, 'content': 'recorded'}}),
        ])
        result = self.parse()
        first, repeated, bad = result['attachments']
        self.assertEqual(first['saved_path'], repeated['saved_path'])
        self.assertEqual(bad['status'], 'unavailable')
        self.assertIsNone(bad['saved_path'])
        write, read = result['recovered_files']
        self.assertEqual(Path(write['saved_path']).read_text(encoding='utf-8'), 'recorded')
        self.assertEqual(write['saved_path'], read['saved_path'])


class ClaudeViewerTest(unittest.TestCase):
    def test_claude_tab_discovers_on_worker_and_renders_scrollable_execution_and_safe_links(self):
        try:
            root = App()
        except tk.TclError as error:
            if 'display' in str(error):
                self.skipTest(str(error))
            raise
        self.addCleanup(root.destroy)
        root.geometry('1000x700+10000+10000')
        pane = root.claude
        root.tabs.select(pane)
        self.assertEqual([root.tabs.tab(tab, 'text') for tab in root.tabs.tabs()],
                         ['Codex', 'OpenCode', 'Claude Code', 'Antigravity'])
        self.assertEqual(len({root.codex.worker, root.opencode.worker, pane.worker}), 3)
        root.codex.result, root.opencode.result = {'codex': True}, {'opencode': True}
        worker_ids = []
        load, parse = claude.load_threads, claude.reconstruct_from_thread

        def load_on_worker(*args):
            worker_ids.append(threading.get_ident())
            return load(*args)

        def parse_on_worker(*args):
            worker_ids.append(threading.get_ident())
            return parse(*args)

        def wait_for(predicate):
            until = time.monotonic() + 8
            while not predicate() and time.monotonic() < until:
                root.update()
                time.sleep(.01)
            self.assertTrue(predicate())
            root.update()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        long_output = 'recorded line\n' * 300 + 'last output line'
        with tempfile.TemporaryDirectory() as temporary:
            index, _, output = build_fixture(Path(temporary), long_output)
            with patch.object(claude, 'load_threads', side_effect=load_on_worker), patch.object(
                claude, 'reconstruct_from_thread', side_effect=parse_on_worker
            ):
                pane.db_path.set(str(index))
                pane.output_root.set(str(output))
                pane._load()
                wait_for(lambda: not pane._working)
                self.assertIsNone(pane.result)
                self.assertEqual(len(worker_ids), 1)
                self.assertEqual(pane.conversations.item('0', 'values')[1:3], ('Create hello.txt', PROJECT))
                pane.conversations.selection_set('0')
                wait_for(lambda: pane.result is not None and pane._render_timer is None)

            widgets = list(descendants(pane.canvas))
            labels = [widget for widget in widgets if isinstance(widget, tk.Label)]
            strings = [widget.cget('text') for widget in labels]
            self.assertTrue({'USER', 'AGENT', 'EXECUTION · WRITE', 'AGENT ERROR'}.issubset(strings))
            self.assertFalse(any('Call ID' in text or 'call-write' in text or 'MESSAGE EVIDENCE' in text
                                 for text in strings))
            self.assertFalse(any(text.startswith(('Started:', 'Ended:')) or text == 'Metadata'
                                 for text in strings))
            edit, = (entry for entry in entries_for(pane.result) if entry.get('call_id') == 'call-edit')
            self.assertIn('structuredPatch', edit['execution']['metadata'])
            self.assertTrue(any(label.cget('text').startswith('hello.txt') and label.cget('cursor') == 'hand2'
                                for label in labels))
            body, = (widget for widget in widgets if isinstance(widget, tk.Text)
                     and widget.get('end-1c linestart', 'end-1c') == 'last output line')
            self.assertEqual(body.get('1.0', 'end-1c'), long_output)
            self.assertEqual(int(body['height']), 9)
            bash, = (entry for entry in entries_for(pane.result) if entry.get('call_id') == 'call-bash')
            item, _ = pane._row_cache[id(bash)]
            pane.canvas.yview_moveto(pane.canvas.coords(item)[1] / pane._content_height)
            root.update()
            self.assertTrue(body.winfo_ismapped())
            outer = pane.canvas.yview()
            body.event_generate('<MouseWheel>', delta=-120)
            self.assertGreater(body.yview()[0], 0)
            self.assertEqual(pane.canvas.yview(), outer)
            body.yview_moveto(1)
            body.event_generate('<MouseWheel>', delta=-120)
            self.assertGreater(pane.canvas.yview()[0], outer[0])

        self.assertEqual(len(worker_ids), 2)
        self.assertEqual(*worker_ids)
        self.assertNotEqual(worker_ids[0], threading.get_ident())
        self.assertEqual(root.codex.result, {'codex': True})
        self.assertEqual(root.opencode.result, {'opencode': True})
