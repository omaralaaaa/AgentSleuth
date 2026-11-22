"""Application entry point and Tk root initialization."""

import queue
from pathlib import Path
import tkinter as tk

from .layout import LayoutMixin
from .controller import ControllerMixin
from .conversation import ConversationMixin


class App(LayoutMixin, ControllerMixin, ConversationMixin, tk.Tk):
    BG = '#0d1422'
    PANEL = '#142034'
    FG = '#ebf2fc'
    DIM = '#a5b4cb'
    ACCENT = '#4bd8b2'
    BORDER = '#30415b'

    def __init__(self):
        super().__init__()
        self.title('AgentSleuth — Codex Forensic Conversation Viewer')
        self.geometry('1390x830')
        self.minsize(900, 620)
        self.configure(bg=self.BG)
        self.db_path = tk.StringVar()
        self.output_root = tk.StringVar(value=str(Path(__file__).resolve().parents[2] / 'AgentSleuth_Results'))
        self.status = tk.StringVar(value='Select Codex state_5.sqlite to load conversations')
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
        self.after(100, self._poll)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
