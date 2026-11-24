"""Application entry point and Tk root initialization."""

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk

from .layout import LayoutMixin
from ..core.export import preference_path, read_export_root, save_export_root, validate_export_root
from ..parsers import antigravity, claude, codex, opencode
from .controller import ControllerMixin
from .conversation import ConversationMixin
from .worker import AgentWorker
from .discovery import ScanDialog


class AgentPane(LayoutMixin, ControllerMixin, ConversationMixin, tk.Frame):
    def __init__(self, parent, parser, output_root, *, closable=False):
        super().__init__(parent, bg=self.BG)
        self.parser = parser
        self.closable = closable
        self.uses_output_directory = getattr(parser, 'uses_output_directory', True)
        self.db_path = tk.StringVar(self)
        self.output_root = output_root if self.uses_output_directory else None
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
        self._render_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f'{parser.name}-render')
        self._plan_cancel = self._plan_future = None
        self._command_styles = {}
        self._row_cache = {}
        self._build()
        self._poll_timer = self.after(100, self._poll)

    def destroy(self):
        self._cancel_render()
        self._render_pool.shutdown(wait=False, cancel_futures=True)
        self.worker.close()
        for timer in (self._filter_timer, self._search_timer, self._layout_timer,
                      self._render_timer, self._poll_timer):
            if timer is not None:
                self.after_cancel(timer)
        for sequence in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
            self.unbind_class(self._conversation_wheel_tag, sequence)
        super().destroy()


class App(LayoutMixin, tk.Tk):
    def __init__(self, parser=codex, *, opencode_parser=opencode, claude_parser=claude,
                 antigravity_parser=antigravity, script_directory=None):
        super().__init__()
        self.title('AgentSleuth — Forensic Conversation Viewer')
        self.geometry('1390x830')
        self.minsize(900, 620)
        self.configure(bg=self.BG)
        self._style()
        self._build_masthead()
        script_directory = (Path(script_directory).resolve() if script_directory is not None
                            else Path(__file__).resolve().parents[2])
        self._export_preference = preference_path()
        output_root, export_error = None, None
        try:
            output_root = read_export_root(script_directory, self._export_preference)
            validate_export_root(output_root)
        except (OSError, RuntimeError, ValueError) as error:
            export_error = f'Could not validate export directory · {error}'
        self.output_root = tk.StringVar(self, value=str(output_root) if output_root is not None else '')
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill='both', expand=True, padx=12, pady=(0, 8))
        self.codex = AgentPane(self.tabs, parser, self.output_root)
        self.opencode = AgentPane(self.tabs, opencode_parser, self.output_root)
        self.claude = AgentPane(self.tabs, claude_parser, self.output_root)
        self.tabs.add(self.codex, text=parser.name)
        self.tabs.add(self.opencode, text=opencode_parser.name)
        self.tabs.add(self.claude, text=claude_parser.name)
        self.antigravity = AgentPane(self.tabs, antigravity_parser, self.output_root)
        self.tabs.add(self.antigravity, text=antigravity_parser.name)
        self._agent_panes = [self.codex, self.opencode, self.claude, self.antigravity]
        if export_error:
            for pane in self._agent_panes:
                if pane.uses_output_directory:
                    pane.status.set(export_error)
        self.bind('<Control-f>', self._focus_search)

    def _set_export_root(self, path):
        root = Path(path).expanduser().absolute()
        validate_export_root(root)
        warning = None
        try:
            save_export_root(self._export_preference, root)
        except (OSError, ValueError) as error:
            warning = f'Export directory selected for this run · could not save preference ({error})'
        if str(root) != self.output_root.get():
            self.output_root.set(str(root))
            for pane in self._agent_panes:
                if pane.uses_output_directory:
                    pane._export_root_changed()
        return warning

    def open_scanner(self):
        if getattr(self, 'scanner', None) is None or not self.scanner.winfo_exists():
            self.scanner = ScanDialog(self)
        self.scanner.lift()
        self.scanner.focus_set()

    def open_evidence_sources(self, sources, evidence_root):
        """Keep each scanned source and its evidence scope in a separate pane."""
        opened = []
        for hit in sources:
            panes = [pane for pane in self._agent_panes if pane.parser.name == hit.agent]
            if not panes:
                continue
            source = (hit.source, evidence_root)
            existing = next((pane for pane in panes if getattr(pane, 'scan_source', None) == source
                             and (pane.db_path.get() == str(hit.source) if pane._loading
                                  else pane._loaded_db == hit.source)), None)
            if existing is not None:
                opened.append(existing)
                continue

            pane = next((pane for pane in panes if pane._loaded_db is None and not pane._loading), None)
            if pane is None:
                pane = AgentPane(self.tabs, panes[0].parser, self.output_root, closable=True)
                label = f'{hit.agent} · {hit.path.name}'
                current = {self.tabs.tab(tab, 'text') for tab in self.tabs.tabs()}
                title = label
                index = 2
                while title in current:
                    title = f'{label} ({index})'
                    index += 1
                self.tabs.add(pane, text=title)
                self._agent_panes.append(pane)
            pane.scan_source = source
            pane.db_path.set(str(hit.source))
            pane._load()
            opened.append(pane)
        if opened:
            self.tabs.select(opened[0])
        return bool(opened)

    def close_source_tab(self, pane):
        self._agent_panes.remove(pane)
        pane.destroy()

    def _focus_search(self, _event):
        self.nametowidget(self.tabs.select()).search_entry.focus_set()


def main(script_path=None):
    directory = Path(script_path).resolve().parent if script_path is not None else None
    App(script_directory=directory).mainloop()


if __name__ == "__main__":
    main()
