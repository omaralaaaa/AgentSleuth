"""GUI actions: load databases, select threads and coordinate background work."""

import queue
from pathlib import Path
from tkinter import filedialog

from ..core.utils import short
from ..core.search import ALL_ENTRIES, TranscriptIndex
from .worker import load_threads, reconstruct


class ControllerMixin:
    def _browse_db(self):
        path = filedialog.askopenfilename(parent=self, title=self.parser.source_hint,
                                         filetypes=self.parser.filetypes)
        if path:
            self.db_path.set(path)
            self._load()

    def _load_typed_source(self, _event):
        if not self._loading:
            self._load()
        return 'break'

    def _browse_output(self):
        path = filedialog.askdirectory(parent=self, title='Choose export directory',
                                       initialdir=self.output_root.get())
        if path:
            try:
                warning = self.winfo_toplevel()._set_export_root(path)
            except (OSError, RuntimeError, ValueError) as error:
                self.status.set(f'Could not set export directory · {error}')
            else:
                if warning:
                    self.status.set(warning)

    def _export_root_changed(self):
        self.cache.clear()
        if not self._loading and self.current_thread_idx is not None:
            self._open_thread(self.current_thread_idx)

    def _set_busy(self, busy):
        self._working = busy
        if busy:
            self.progress.pack(side='right', padx=(12, 0))
            self.progress.start(30)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _load(self):
        source = self.db_path.get().strip().strip('"')
        if not source:
            self.status.set(self.parser.source_hint)
            return
        self._loading = True
        self._set_busy(True)
        self.status.set(f'Reading {self.parser.name} conversations…')
        self.worker.start('loaded', load_threads, self.parser, Path(source))

    def _display_loaded(self, path, threads):
        source, evidence_root = getattr(self, 'scan_source', (None, None))
        if source == path and evidence_root is not None:
            for thread in threads:
                thread['_evidence_root'] = evidence_root
        self._loaded_db = path
        self.threads = threads
        self.cache.clear()
        self.current_thread_idx = None
        self._active_cache_key = None
        self.result = None
        self._populate_threads()
        self._clear_chat()
        self.thread_title.configure(text='Select a conversation')
        self.thread_cwd.configure(text='')
        self.thread_rollout.configure(text='')
        self._reset_view_options()
        status = f'Loaded {len(threads)} conversations'
        if self.visible_index:
            status += ' · select one to view'
        self.status.set(status)

    def _populate_threads(self):
        old_idx = self.current_thread_idx
        for child in self.conversations.get_children(''):
            self.conversations.delete(child)
        self.visible_index = []
        needle = self.filter_text.get().strip().lower()
        visible_names = []
        for idx, thread in enumerate(self.threads):
            searchable = ' '.join(str(thread.get(key) or '') for key in ('name', 'cwd', 'id'))
            if needle and needle not in searchable.lower():
                continue
            self.visible_index.append(idx)
            visible_names.append(thread.get('name') or 'Unnamed conversation')
            row_number = len(self.visible_index)
            self.conversations.insert(
                '', 'end', iid=str(idx),
                values=(f'{row_number:03d}', visible_names[-1],
                        *(thread.get(key, '') for key, _, _ in self.sidebar_columns)),
                tags=('odd' if row_number % 2 else 'even',)
            )
        # Keep long names available through the sidebar's horizontal scrollbar.
        longest = max((len(name) for name in visible_names), default=24)
        self.conversations.column('name', width=max(225, min(620, longest * 7 + 24)))
        if old_idx in self.visible_index:
            self.conversations.selection_set(str(old_idx))
            self.conversations.see(str(old_idx))
        self.sidebar_info.configure(text=f'{len(self.visible_index)} of {len(self.threads)} conversations')

    def _select_thread(self, _event=None):
        selected = self.conversations.selection()
        if not selected or self._loading or self._loaded_db is None:
            return
        try:
            thread_index = int(selected[0])
        except (TypeError, ValueError):
            return
        if thread_index < 0 or thread_index >= len(self.threads):
            return
        self._open_thread(thread_index)

    def _open_thread(self, thread_index):
        thread = self.threads[thread_index]
        output_root = None
        if self.output_root is not None:
            if not self.output_root.get():
                self.status.set('Choose an export directory before opening a conversation.')
                return
            output_root = Path(self.output_root.get())
        cache_key = (self._loaded_db, thread['id'], output_root)
        if (self.current_thread_idx == thread_index and (self.result is not None or self._working)
                and self._active_cache_key == cache_key):
            return
        self.current_thread_idx = thread_index
        self._active_cache_key = cache_key
        self._display_header(thread)
        self._clear_chat()
        self._reset_view_options()
        if cache_key in self.cache:
            self.worker.invalidate()
            self._set_busy(False)
            self.result = self.cache[cache_key]
            self._after_reconstruct()
            return
        self.result = None
        self._section('Reconstructing selected conversation…')
        source = getattr(self.parser, 'transcript_label',
                         'rollout' if self.uses_output_directory else 'OpenCode evidence')
        self.status.set(f'Reading {source} for {thread["name"]}')
        self._set_busy(True)
        self.worker.start('reconstructed', reconstruct, self.parser, self._loaded_db,
                          thread, output_root)

    def _display_header(self, thread):
        self.thread_title.configure(text=thread['name'])
        self.thread_cwd.configure(text='Working directory (cwd): ' + (thread['cwd'] or 'Unknown'))
        if detail := thread.get('source_detail'):
            self.thread_rollout.configure(text=detail)
        elif self.uses_output_directory:
            self.thread_rollout.configure(text='Rollout: ' + (thread.get('rollout_path') or 'Not recorded'))
        else:
            self.thread_rollout.configure(text=f'Session ID  {thread["id"]}')

    def _reset_view_options(self):
        self.filter_options.configure(values=(ALL_ENTRIES,))
        self.turn_options.configure(values=['Entire conversation'])
        self.turn_options.current(0)
        self.conversation_stats.configure(text='')

    def _turn_changed(self, _event=None):
        if self.result is None:
            return
        selection = self.turn_options.current()
        choices = self._index.turn_filters[selection - 1] if selection > 0 else self._index.filters
        self.filter_options.configure(values=choices)
        if self.entry_type.get() not in choices:
            self.entry_type.set(ALL_ENTRIES)
        self._render()

    def _poll(self):
        for _ in range(45):
            try:
                request, kind, value = self.worker.results.get_nowait()
            except queue.Empty:
                break
            if request != self.worker.request:
                continue
            if kind == 'progress':
                self.status.set(value)
            elif kind == 'loaded':
                self._loading = False
                self._set_busy(False)
                self._display_loaded(*value)
            elif kind == 'reconstructed':
                self._set_busy(False)
                self.cache[self._active_cache_key] = self.result = value
                self._after_reconstruct()
            elif kind == 'error':
                self._loading = False
                self._set_busy(False)
                self.status.set(f'Error reading {self.parser.name} evidence · {value}')
                if self.result is None:
                    self.conversations.selection_remove(self.conversations.selection())
                    self._clear_chat()
                    self._section(value)
        self._poll_timer = self.after(100, self._poll)

    def _after_reconstruct(self):
        if not self.result:
            return
        turns = self.result['turns']
        if detail := self.result.get('source_detail'):
            self.thread_rollout.configure(text=detail)
        self._clear_chat()
        self._index = self.result.get('_search_index') or TranscriptIndex(turns)
        self.turn_options.configure(values=['Entire conversation'] +
                                    [f'{i + 1:02d} · {short(t["title"], 75)}' for i, t in enumerate(turns)])
        self.turn_options.current(0)
        s = self.result['summary']
        self.conversation_stats.configure(text=f'{s["turns"]} turns · {s["activities"]} activities')
        self._turn_changed()

    def _clear_chat(self):
        self._cancel_render()
        self.canvas.delete('all')
        for row in self.canvas.winfo_children():
            row.destroy()
        self._rows.clear()
        self._row_cache.clear()
        self._collapsed_prompts = set()
        self._content_height = 0
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
        self._photos.clear()
        self.canvas.yview_moveto(0)

    def _section(self, label):
        row = self._new_row()
        heading = self._label(row, label, self.DIM, ('Consolas', 10, 'bold'),
                              anchor='w', justify='left', wraplength=750)
        heading.pack(fill='x', padx=18, pady=(18, 4))
        self._bind_conversation_wheel_tree(row)
