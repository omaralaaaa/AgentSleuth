import tkinter as tk
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from agentsleuth.ui.app import App


class ViewerTest(unittest.TestCase):
    def test_progress_runs_during_provider_load_and_hides_on_completion(self):
        release = threading.Event()
        def load_threads(path):
            release.wait(5)
            return []

        provider = SimpleNamespace(name='Fixture', source_label='File', source_hint='Choose a file',
                                   filetypes=[], load_threads=load_threads)
        try:
            app = App(parser=provider)
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(app.destroy)
        self.addCleanup(release.set)
        app.geometry('1000x700+10000+10000')
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
            app = App()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(app.destroy)
        app.geometry('1000x700+10000+10000')
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
            return [w for w in widgets(app.canvas) if isinstance(w, tk.Text)]

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
        app.turn_options.current(4)
        app._render()
        finish_render()
        self.assertEqual(len(bodies()), 11)
