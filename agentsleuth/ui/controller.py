"""GUI actions: load databases, select threads and coordinate background work."""

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

from ..core.utils import short





class ControllerMixin:
    def _browse_db(self):
        path = filedialog.askopenfilename(title=self.parser.source_hint, filetypes=self.parser.filetypes)
        if path:
            self.db_path.set(path)
            self._load()

    def _browse_output(self):
        path = filedialog.askdirectory(title='Choose extracted-files directory', initialdir=self.output_root.get())
        if path:
            self.output_root.set(path)
            self.cache.clear()
            self._active_cache_key = None
            self.result = None
            self.current_thread_idx = None
            if self.conversations.selection():
                self._select_thread()

    def _set_busy(self, busy):
        self._working = busy
        self.load_button.configure(state='disabled' if busy else 'normal')
        if busy:
            self.progress.pack(side='right', padx=(12, 0))
            self.progress.start(30)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _load(self):
        if self._working:
            return
        path = Path(self.db_path.get().strip().strip('"'))
        if not path.is_file():
            messagebox.showerror('Missing source file', self.parser.source_hint)
            return
        self._set_busy(True)
        self.status.set(f'Reading {self.parser.name} conversations…')
        def task():
            try:
                data = self.parser.load_threads(path)
                self.messages_queue.put(('loaded', data))
            except Exception as error:
                self.messages_queue.put(('error', str(error)))
        threading.Thread(target=task, daemon=True).start()

    def _populate_threads(self):
        old_idx = self.current_thread_idx
        for child in self.conversations.get_children(''):
            self.conversations.delete(child)
        self.visible_index = []
        needle = self.filter_text.get().strip().lower()
        visible_names = []
        for idx, thread in enumerate(self.threads):
            searchable = ' '.join((thread.get('name', ''), thread.get('cwd', ''), thread.get('id', '')))
            if needle and needle not in searchable.lower():
                continue
            self.visible_index.append(idx)
            visible_names.append(thread.get('name') or 'Unnamed conversation')
            row_number = len(self.visible_index)
            self.conversations.insert(
                '', 'end', iid=str(idx),
                values=(f'{row_number:03d}', visible_names[-1]),
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
        if not selected or self._working:
            return
        try:
            thread_index = int(selected[0])
        except (TypeError, ValueError):
            return
        if thread_index < 0 or thread_index >= len(self.threads):
            return
        thread = self.threads[thread_index]
        cache_key = (thread['id'], thread['rollout_path'], self.output_root.get())
        if (self.current_thread_idx == thread_index and self.result is not None
                and self._active_cache_key == cache_key):
            return
        self.current_thread_idx = thread_index
        self._active_cache_key = cache_key
        self._display_header(thread)
        self._clear_chat()
        self._section('Reconstructing selected conversation…')
        self.status.set(f'Reading rollout for: {thread["name"]}')
        if cache_key in self.cache:
            self.result = self.cache[cache_key]
            self._after_reconstruct()
            return
        self.result = None
        selected_db = Path(self.db_path.get())
        selected_root = Path(self.output_root.get())
        self._set_busy(True)
        def task():
            try:
                data = self.parser.reconstruct_from_thread(
                    selected_db, thread, selected_root,
                    lambda s: self.messages_queue.put(('progress', s)))
                self.messages_queue.put(('reconstructed', (thread_index, cache_key, data)))
            except Exception as error:
                self.messages_queue.put(('parse_error', str(error)))
        threading.Thread(target=task, daemon=True).start()

    def _display_header(self, thread):
        self.thread_title.configure(text=thread['name'])
        self.thread_permissions.configure(text='Permissions: ' + thread['permissions'] +
                                          ('   |   Approval: ' + str(thread['approval_policy']) if thread['approval_policy'] else ''))
        self.thread_cwd.configure(text='Working directory (cwd): ' + (thread['cwd'] or 'Unknown'))
        self.thread_rollout.configure(text='Rollout: ' + (thread['rollout_path'] or 'Not recorded'))

    def _poll(self):
        for _ in range(45):
            try:
                kind, value = self.messages_queue.get_nowait()
            except queue.Empty:
                break
            if kind == 'progress':
                self.status.set(value)
            elif kind == 'loaded':
                self._set_busy(False)
                self.threads = value
                self.current_thread_idx = None
                self._active_cache_key = None
                self.result = None
                self.cache.clear()
                self._populate_threads()
                self._clear_chat()
                self.thread_title.configure(text='Select a conversation')
                self.thread_permissions.configure(text='')
                self.thread_cwd.configure(text='')
                self.thread_rollout.configure(text='')
                self.turn_options.configure(values=['Entire conversation'])
                self.turn_options.current(0)
                self.conversation_stats.configure(text='')
                if self.threads and self.conversations.get_children(''):
                    self.status.set(
                        f'Loaded {len(value)} conversations · select one to view'
                    )
                else:
                    self.status.set(f'Loaded {len(value)} conversations')
            elif kind == 'reconstructed':
                self._set_busy(False)
                idx, key, result = value
                self.cache[key] = result
                if self.current_thread_idx == idx:
                    self.result = result
                    self._after_reconstruct()
            elif kind in {'error', 'parse_error'}:
                self._set_busy(False)
                self.status.set('Error while loading evidence')
                messagebox.showerror('AgentSleuth', str(value))
        self._poll_timer = self.after(100, self._poll)

    def _after_reconstruct(self):
        if not self.result:
            return
        turns = self.result['turns']
        self.turn_options.configure(values=['Entire conversation'] +
                                    [f'{i + 1:02d} · {short(t["title"], 75)}' for i, t in enumerate(turns)])
        self.turn_options.current(0)
        s = self.result['summary']
        self.conversation_stats.configure(text=f'{s["turns"]} turns · {s["activities"]} activities')
        self.status.set(f'Conversation loaded · {s["attachments"]} embedded attachments · '
                        f'{s["recovered_files"]} file changes rebuilt · '
                        f'{s["max_ordinal"]} max ordinal')
        self._render()

    def _clear_chat(self):
        if self._render_timer is not None:
            self.after_cancel(self._render_timer)
            self._render_timer = None
        self.canvas.delete('all')
        for _, row in self._rows:
            row.destroy()
        self._rows.clear()
        self._content_height = 0
        self.canvas.configure(scrollregion=(0, 0, 0, 0))
        self._photos.clear()
        self.canvas.yview_moveto(0)

    def _section(self, label):
        heading = self._label(self._new_row(), label, self.DIM, ('Consolas', 10, 'bold'),
                              anchor='w', justify='left', wraplength=750)
        heading.pack(fill='x', padx=18, pady=(18, 4))
        self._bind_conversation_wheel_tree(heading)
