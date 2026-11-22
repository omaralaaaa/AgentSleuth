"""Application entry point and Tk root initialization."""

import queue
from pathlib import Path
import tkinter as tk

from .layout import LayoutMixin
from ..parsers import codex
from .controller import ControllerMixin
from .conversation import ConversationMixin


class App(LayoutMixin, ControllerMixin, ConversationMixin, tk.Tk):
    BG = '#191b1f'
    PANEL = '#23262b'
    FG = '#dee1e5'
    DIM = '#adb3bc'
    ACCENT = '#99b5d3'
    BORDER = '#454a53'

    def __init__(self, parser=codex):
        super().__init__()
        self.parser = parser
        self.title(f'AgentSleuth — {parser.name} Forensic Conversation Viewer')
        self.geometry('1390x830')
        self.minsize(900, 620)
        self.configure(bg=self.BG)
        self.db_path = tk.StringVar()
        self.output_root = tk.StringVar(value=str(Path(__file__).resolve().parents[2] / 'AgentSleuth_Results'))
        self.status = tk.StringVar(value=parser.source_hint)
        self.filter_text = tk.StringVar()
        self.threads = []
        self.visible_index = []
        self.current_thread_idx = None
        self._active_cache_key = None
        self.result = None
        self.cache = {}
        self.messages_queue = queue.Queue()
        self._photos = []
        self._working = False
        self._style()
        self._build()
        self._poll_timer = self.after(100, self._poll)

    def destroy(self):
        self.after_cancel(self._poll_timer)
        super().destroy()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
