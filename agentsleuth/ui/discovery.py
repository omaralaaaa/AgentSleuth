"""Background artifact scan and source picker."""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, ttk

from ..core.discovery import live_roots, scan


UNCHECKED = '☐'
CHECKED = '☑'


class ScanDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.title('Discover agent evidence')
        self.geometry('930x480')
        self.minsize(530, 300)
        self.configure(bg=app.PANEL)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.transient(app)
        self.app = app
        self.job = None
        self.timer = None
        self.findings = []
        self.root_path = None
        self.status = tk.StringVar(value='Scan known locations on this PC or select an extracted evidence folder.')
        bar = ttk.Frame(self, padding=8)
        bar.grid(row=0, column=0, sticky='ew')
        ttk.Button(bar, text='Scan this PC', command=lambda: self.start(None)).pack(side='left')
        ttk.Button(bar, text='Scan evidence folder…', command=self.choose).pack(side='left', padx=6)
        ttk.Label(self, textvariable=self.status, padding=8, wraplength=490).grid(row=1, column=0, sticky='ew')
        frame = ttk.Frame(self)
        frame.grid(row=2, column=0, sticky='nsew', padx=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(frame, columns=('check', 'agent', 'path', 'status'), show='headings',
                                  style='Conversations.Treeview', selectmode='none')
        for col, label, width in [('check', 'Select', 64), ('agent', 'Agent', 125), ('path', 'Evidence folder', 500),
                                  ('status', 'Source', 210)]:
            self.table.heading(col, text=label, anchor='w')
            self.table.column(col, width=width, minwidth=width, stretch=col == 'path',
                              anchor='center' if col == 'check' else 'w')
        scroll = ttk.Scrollbar(frame, command=self.table.yview)
        across = ttk.Scrollbar(frame, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        scroll.grid(row=0, column=1, sticky='ns')
        across.grid(row=1, column=0, sticky='ew')
        self.table.grid(row=0, column=0, sticky='nsew')
        footer = ttk.Frame(self, padding=(8, 6))
        footer.grid(row=3, column=0, sticky='ew')
        self.open_button = ttk.Button(footer, text='Open selected', style='Accent.TButton',
                                      state='disabled', command=self.open_source)
        self.open_button.pack(side='right')
        self.select_all_button = ttk.Button(footer, text='Select all', width=15, state='disabled',
                                             command=self._toggle_all)
        self.select_all_button.pack(side='right', padx=(0, 6))
        self.table.bind('<Button-1>', self._click_row)
        self.table.bind('<Double-1>', self._open_clicked_source)
        self.table.bind('<Return>', self.open_source)
        self.table.bind('<space>', self._toggle_focused)
        self.table.bind('<Control-a>', self._select_all)

    def choose(self):
        value = filedialog.askdirectory(parent=self, title='Select an extracted C: drive or collection folder')
        if value:
            self.start(Path(value).resolve())

    def _stop_scan(self):
        if self.job is not None:
            self.job.set()
            self.job = None
        if self.timer is not None:
            self.after_cancel(self.timer)
            self.timer = None

    def destroy(self):
        self._stop_scan()
        super().destroy()

    def start(self, root):
        self._stop_scan()
        job = self.job = threading.Event()
        events = queue.Queue()
        self.root_path = root
        self.findings = []
        self.table.delete(*self.table.get_children())
        self._set_checked(set())
        self.status.set(f'Scanning {root or "known agent locations on this PC"}…')
        def work():
            try:
                result = scan([root] if root else live_roots(), job,
                              lambda dirs, hits: events.put(('progress', f'{dirs:,} directories scanned · {hits:,} agent folders')),
                              known_locations=root is None)
                events.put(('done', result))
            except Exception as error:
                events.put(('error', str(error)))
        def poll():
            self.timer = None
            try:
                while True:
                    kind, value = events.get_nowait()
                    if kind == 'progress':
                        self.status.set(value)
                        continue
                    self.job = None
                    if kind == 'error':
                        self.status.set(f'Scan failed · {value}')
                        return
                    self.findings, skipped = value
                    path_font = font.Font(self, font=ttk.Style(self).lookup('Conversations.Treeview', 'font'))
                    width = max((path_font.measure(str(hit.path)) + 24 for hit in self.findings), default=500)
                    self.table.column('path', width=max(500, width), minwidth=max(300, width))
                    for idx, hit in enumerate(self.findings):
                        mark = UNCHECKED if hit.source is not None else ''
                        self.table.insert('', 'end', iid=str(idx), values=(mark, hit.agent, str(hit.path), hit.status))
                    if self.findings and self.findings[0].source:
                        self.table.focus('0')
                    self._set_checked(set())
                    self.status.set(f'Complete · {len(self.findings):,} agent folders · '
                                    f'{skipped:,} inaccessible directories')
                    return
            except queue.Empty:
                self.timer = self.after(100, poll)
        threading.Thread(target=work, daemon=True).start()
        self.timer = self.after(100, poll)

    def _set_checked(self, rows):
        before = set(self.table.selection())
        for row in before - rows:
            self.table.set(row, 'check', UNCHECKED)
        for row in rows - before:
            self.table.set(row, 'check', CHECKED)
        self.table.selection_set(*rows)
        self.open_button.configure(state='normal' if rows else 'disabled')
        available = self._available_rows()
        all_checked = bool(available) and rows == available
        self.select_all_button.configure(text='Clear selection' if all_checked else 'Select all',
                                         state='normal' if available else 'disabled')

    def _available_rows(self):
        return {str(index) for index, hit in enumerate(self.findings) if hit.source is not None}

    def _toggle_all(self):
        available = self._available_rows()
        self._set_checked(set() if set(self.table.selection()) == available else available)

    def _toggle(self, row):
        if row and self.findings[int(row)].source is not None:
            self._set_checked(set(self.table.selection()) ^ {row})

    def _checkbox_at(self, event):
        return (self.table.identify_region(event.x, event.y) == 'cell'
                and self.table.identify_column(event.x) == '#1')

    def _click_row(self, event):
        if self.table.identify_region(event.x, event.y) != 'cell':
            return
        if row := self.table.identify_row(event.y):
            self.table.focus_set()
            self.table.focus(row)
            self._toggle(row)
            return 'break'

    def _toggle_focused(self, _event):
        self._toggle(self.table.focus())
        return 'break'

    def _select_all(self, _event=None):
        self._set_checked(self._available_rows())
        return 'break'

    def _open_clicked_source(self, event):
        if row := self.table.identify_row(event.y):
            hit = self.findings[int(row)]
            if not self._checkbox_at(event) and hit.source is not None:
                self._open_sources([hit])
            return 'break'

    def open_source(self, _event=None):
        selected = (self.findings[index] for index in sorted(map(int, self.table.selection())))
        self._open_sources([hit for hit in selected if hit.source is not None])
        return 'break'

    def _open_sources(self, sources):
        if sources and self.app.open_evidence_sources(sources, self.root_path):
            self.destroy()
