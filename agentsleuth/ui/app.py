"""Application entry point and Tk root initialization."""

from pathlib import Path
import tkinter as tk
from tkinter import ttk

from .layout import LayoutMixin
from ..parsers import codex, opencode
from .controller import ControllerMixin
from .conversation import ConversationMixin
from .worker import AgentWorker


class AgentPane(LayoutMixin, ControllerMixin, ConversationMixin, tk.Frame):
    def __init__(self, parent, parser):
        super().__init__(parent, bg=self.BG)
        self.parser = parser
        self.uses_output_directory = getattr(parser, 'uses_output_directory', True)
        self.db_path = tk.StringVar(self)
        self.output_root = tk.StringVar(
            self, value=str(Path(__file__).resolve().parents[2] / 'AgentSleuth_Results')
        ) if self.uses_output_directory else None
        self.status = tk.StringVar(self, value=parser.source_hint)
        self.filter_text = tk.StringVar(self)
        self.threads = []
        self.visible_index = []
        self.current_thread_idx = None
        self._active_cache_key = None
        self._loaded_db = None
        self.result = None
        self.cache = {}
        self.worker = AgentWorker(parser.name)
        self._photos = []
        self._working = False
        self._loading = False
        self._render_timer = None
        self._row_cache = {}
        self._build()
        self._poll_timer = self.after(100, self._poll)

    def destroy(self):
        self.worker.close()
        for timer in (self._filter_timer, self._search_timer, self._layout_timer,
                      self._render_timer, self._poll_timer):
            if timer is not None:
                self.after_cancel(timer)
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.unbind_class(self._conversation_wheel_tag, sequence)
        super().destroy()


class App(LayoutMixin, tk.Tk):
    def __init__(self, parser=codex, *, opencode_parser=opencode):
        super().__init__()
        self.title('AgentSleuth — Forensic Conversation Viewer')
        self.geometry('1390x830')
        self.minsize(900, 620)
        self.configure(bg=self.BG)
        self._style()
        self._build_masthead()
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.codex = AgentPane(self.tabs, parser)
        self.opencode = AgentPane(self.tabs, opencode_parser)
        self.tabs.add(self.codex, text=parser.name)
        self.tabs.add(self.opencode, text=opencode_parser.name)
        self.bind('<Control-f>', self._focus_search)

    def _focus_search(self, _event):
        self.nametowidget(self.tabs.select()).search_entry.focus_set()


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
