import tkinter as tk
import unittest

from agentsleuth.ui.app import App


class ViewerTest(unittest.TestCase):
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
