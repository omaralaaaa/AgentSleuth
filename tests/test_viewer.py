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

    def test_large_transcript_pages_and_expands_losslessly(self):
        try:
            app = App()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(app.destroy)
        app.geometry('1000x700+10000+10000')
        body = 'line of output\n' * 200
        turns = []
        for i in range(100):
            entries = [dict(kind='message', role='user', ordinal=i*11+j, text=body)
                       for j in range(11)]
            turns.append(dict(title=str(i), entries=entries))
        app.result = dict(turns=turns, summary=dict(turns=100, activities=0,
                          attachments=0, recovered_files=0, max_ordinal=1099),
                          output_directory='.')
        app._after_reconstruct()
        app.update()

        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)

        def bodies():
            return [w for w in widgets(app.chat_frame) if isinstance(w, tk.Text)]

        self.assertEqual(len(bodies()), app.PAGE_SIZE)
        first = bodies()[0]
        self.assertLess(len(first.get('1.0', 'end-1c')), len(body))
        first.master.winfo_children()[-1].invoke()
        app.update()
        self.assertEqual(first.get('1.0', 'end-1c'), body)
        self.assertGreaterEqual(int(first['height']), 201)
        app._render(page=54)
        app.update()
        self.assertIn('1081', app.status.get())
        app.turn_options.current(100)
        app._render()
        app.update()
        self.assertEqual(len(bodies()), 11)
