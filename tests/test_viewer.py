import tkinter as tk
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agentsleuth.ui.app import App
from agentsleuth.ui.powershell import insert_command, is_powershell
from agentsleuth.ui.render_plan import build_plan


def wait_render(pane):
    deadline = time.monotonic() + 5
    while pane._render_timer is not None and time.monotonic() < deadline:
        pane.update()
        time.sleep(.005)
    if pane._render_timer is not None:
        raise AssertionError('Render did not finish')


class ViewerTest(unittest.TestCase):
    def test_slow_render_plan_is_replaced_while_tk_stays_responsive(self):
        try:
            root = App()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        root.withdraw()
        pane = root.codex
        started, release = threading.Event(), threading.Event()
        threads = []
        def delayed(*args):
            threads.append(threading.get_ident())
            if len(threads) == 1:
                started.set()
                release.wait(5)
            return build_plan(*args)
        entry = dict(kind='message', role='user', ordinal=1, text='first request')
        pane.result = dict(turns=[dict(title='Example', entries=[entry])],
                           summary=dict(turns=1, activities=0))
        with patch('agentsleuth.ui.conversation.build_plan', side_effect=delayed):
            pane._after_reconstruct()
            try:
                self.assertTrue(started.wait(2))
                pane.entry_type.set('Commands')
                pane._render()
                heartbeat = []
                pane.after_idle(lambda: heartbeat.append(True))
                pane.update()
                self.assertEqual(heartbeat, [True])
            finally:
                release.set()
            wait_render(pane)
        self.assertTrue(all(t != threading.get_ident() for t in threads))
        self.assertEqual(set(pane._row_cache), {'empty'})

    def test_prompt_folds_only_its_replies_and_tools(self):
        try:
            root = App()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        root.geometry('1000x700+10000+10000')
        app = root.codex
        first, reply, second, later = [
            dict(kind='message', role=role, ordinal=n, text=str(n))
            for n, role in [(1, 'user'), (2, 'assistant'), (4, 'user'), (5, 'assistant')]
        ]
        tool = dict(kind='activity', activity_type='McpToolCall', ordinal=3, item={})
        app.result = dict(turns=[dict(title='Shared turn', entries=[first, reply, tool, second, later])],
                          summary=dict(turns=1, activities=1, attachments=0, recovered_files=0,
                                       max_ordinal=5), output_directory='.')
        app._after_reconstruct()
        wait_render(app)
        app.update()
        def button_under(widget):
            if widget.winfo_class() == 'TButton':
                return widget
            for child in widget.winfo_children():
                button = button_under(child)
                if button is not None:
                    return button
        button = button_under(app._row_cache[id(first)][1])
        button.invoke()
        wait_render(app)
        def visible(entry):
            return app._row_cache[id(entry)] in app._rows
        self.assertEqual([visible(e) for e in (first, reply, tool, second, later)],
                         [True, False, False, True, True])
        app.entry_type.set('Tool calls')
        app._render()
        wait_render(app)
        self.assertTrue(visible(first))
        self.assertFalse(visible(tool))
        button.invoke()
        wait_render(app)
        self.assertTrue(visible(tool))
        self.assertTrue(visible(first))
        self.assertFalse(visible(second))
        app.update()
        def card_left(entry):
            row = app._row_cache[id(entry)][1]
            holder = row.winfo_children()[0]
            return holder.winfo_children()[-1].winfo_x()
        self.assertGreater(card_left(tool), card_left(first))
        app.entry_type.set('All entries')
        app._render()
        wait_render(app)
        self.assertTrue(all(visible(e) for e in (first, reply, tool, second, later)))
        button.invoke()
        app.view_buttons['Conversation'].invoke()
        wait_render(app)
        self.assertTrue(all(visible(e) for e in (first, reply, tool, second, later)))
        self.assertIsNone(button_under(app._row_cache[id(first)][1]))
        self.assertEqual([app._row_cache[id(e)] for e in (first, reply, tool, second, later)], app._rows)
        app.entry_type.set('Tool calls')
        app._render()
        wait_render(app)
        self.assertEqual(app._rows, [app._row_cache[id(tool)]])
        app.view_buttons['Tree'].invoke()
        wait_render(app)
        self.assertEqual(app.entry_type.get(), 'Tool calls')
        self.assertTrue(visible(first))
        self.assertIn(id(first), app._collapsed_prompts)
        self.assertNotIn(id(tool), app._row_cache)
        self.assertEqual(root.opencode.view_mode, 'Tree')

    def test_powershell_highlighting_preserves_command_text(self):
        command = "Get-Item -Path $target | Select-Object 'Name' # café"
        self.assertTrue(is_powershell([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
                                       '-Command', command], command))
        self.assertFalse(is_powershell(['bash', '-c', command], command))
        try:
            root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        root.withdraw()
        text = tk.Text(root)
        insert_command(text, command)
        self.assertEqual(text.get('1.0', 'end-1c'), command)
        for tag, expected in [('command', ['Get-Item', 'Select-Object']), ('parameter', ['-Path']),
                              ('variable', ['$target']), ('string', ["'Name'"]), ('comment', ['# café'])]:
            ranges = iter(text.tag_ranges(tag))
            self.assertEqual([text.get(start, end) for start, end in zip(ranges, ranges)], expected)

    def test_progress_runs_during_provider_load_and_hides_on_completion(self):
        release = threading.Event()
        def load_threads(path):
            release.wait(5)
            return []

        provider = SimpleNamespace(name='Fixture', source_label='File', source_hint='Choose a file',
                                   filetypes=[], load_threads=load_threads)
        try:
            root = App(parser=provider)
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        self.addCleanup(release.set)
        root.geometry('1000x700+10000+10000')
        app = root.codex
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'sample'
            source.touch()
            app.db_path.set(str(source))
            app._load()
            app.update()
            self.assertTrue(app.progress.winfo_ismapped())
            initial = app.progress['value']
            deadline = time.monotonic() + 2
            while app.progress['value'] == initial and time.monotonic() < deadline:
                app.update()
                time.sleep(.01)
            self.assertNotEqual(initial, app.progress['value'])
            release.set()
            deadline = time.monotonic() + 2
            while app._working and time.monotonic() < deadline:
                app.update()
                time.sleep(.01)
            self.assertFalse(app._working)
            self.assertFalse(app.progress.winfo_ismapped())

    def test_continuous_transcript_and_nested_scrolling(self):
        try:
            root = App()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(root.destroy)
        root.geometry('1000x700+10000+10000')
        app = root.codex
        body = 'line of output\n' * 200
        turns = []
        for i in range(20):
            entries = [dict(kind='message', role='user', ordinal=i*11+j, text=body)
                       for j in range(11)]
            turns.append(dict(title=str(i), entries=entries))
        turns[-1]['entries'][-1]['text'] = 'Last short message'
        app.result = dict(turns=turns, summary=dict(turns=20, activities=0,
                          attachments=0, recovered_files=0, max_ordinal=219),
                          output_directory='.')
        app._after_reconstruct()
        app.update()

        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)

        def bodies():
            return [w for _, row in app._rows for w in widgets(row) if isinstance(w, tk.Text)]

        def finish_render():
            deadline = time.monotonic() + 10
            while app._render_timer is not None and time.monotonic() < deadline:
                app.update()
                time.sleep(.01)
            app.update()
            self.assertIsNone(app._render_timer)

        finish_render()
        self.assertEqual(len(bodies()), 220)
        self.assertGreater(app._content_height, 32767)
        app.canvas.yview_moveto(1)
        app.update()
        last = bodies()[-1]
        self.assertTrue(last.winfo_ismapped(), (app.canvas.yview(), app.canvas.bbox(app._rows[-1][0]),
                                                app._content_height, app.canvas.winfo_height()))
        self.assertTrue(0 <= last.winfo_rooty() - app.canvas.winfo_rooty() < app.canvas.winfo_height())
        app.canvas.yview_moveto(0)
        app.update()
        self.assertEqual(int(bodies()[-1]['height']), 1)
        first = bodies()[0]
        self.assertEqual(first.get('1.0', 'end-1c'), body)
        self.assertEqual(int(first['height']), 12)
        outer = app.canvas.yview()
        first.event_generate('<MouseWheel>', delta=-120)
        self.assertGreater(first.yview()[0], 0)
        self.assertEqual(app.canvas.yview(), outer)
        first.yview_moveto(1)
        first.event_generate('<MouseWheel>', delta=-120)
        self.assertGreater(app.canvas.yview()[0], outer[0])
        last_body = bodies()[-1]
        app.query.set('SHORT last')
        def settle_filters():
            deadline = time.monotonic() + 2
            while app._search_timer is not None and time.monotonic() < deadline:
                app.update()
                time.sleep(.01)
            finish_render()
        settle_filters()
        self.assertEqual(bodies(), [last_body])
        app.entry_type.set('Commands')
        settle_filters()
        self.assertEqual(bodies(), [])
        self.assertIn('0 matching', app.status.get())
        app.entry_type.set('All entries')
        app.query.set('')
        settle_filters()
        self.assertEqual(bodies()[0], first)
        app.turn_options.current(4)
        app._render()
        finish_render()
        self.assertEqual(len(bodies()), 11)
