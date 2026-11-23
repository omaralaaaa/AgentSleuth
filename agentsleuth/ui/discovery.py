"""Background artifact scan and source picker."""

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font, ttk

from ..core.discovery import live_roots, scan


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
        ttk.Button(bar, text='Cancel scan', command=self.cancel).pack(side='right')
        ttk.Label(self, textvariable=self.status, padding=8, wraplength=490).grid(row=1, column=0, sticky='ew')
        frame = ttk.Frame(self)
        frame.grid(row=2, column=0, sticky='nsew', padx=8)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(frame, columns=('agent', 'path', 'status'), show='headings',
                                  style='Conversations.Treeview', selectmode='browse')
        for col, label, width in [('agent', 'Agent', 125), ('path', 'Evidence folder', 500),
                                  ('status', 'Source', 210)]:
            self.table.heading(col, text=label, anchor='w')
            self.table.column(col, width=width, minwidth=width, stretch=col == 'path')
        scroll = ttk.Scrollbar(frame, command=self.table.yview)
        across = ttk.Scrollbar(frame, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=across.set)
        scroll.grid(row=0, column=1, sticky='ns')
        across.grid(row=1, column=0, sticky='ew')
        self.table.grid(row=0, column=0, sticky='nsew')
        self.open_button = ttk.Button(self, text='Open folder', style='Accent.TButton',
                                      state='disabled', command=self.open_source)
        self.open_button.grid(row=3, column=0, sticky='e', padx=8, pady=6)
        self.table.bind('<<TreeviewSelect>>', self.select)
        self.table.bind('<Double-1>', self.open_source)
        self.table.bind('<Return>', self.open_source)

    def choose(self):
        value = filedialog.askdirectory(parent=self, title='Select an extracted C: drive or collection folder')
        if value:
            self.start(Path(value).resolve())

    def cancel(self):
        if self.job:
            self.job.set()
            self.status.set('Cancelling scan…')

    def destroy(self):
        self.cancel()
        if self.timer is not None:
            self.after_cancel(self.timer)
        super().destroy()

    def start(self, root):
        self.cancel()
        if self.timer is not None:
            self.after_cancel(self.timer)
        job = self.job = threading.Event()
        events = queue.Queue()
        self.root_path = root
        self.findings = []
        self.table.delete(*self.table.get_children())
        self.open_button.configure(state='disabled')
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
                        self.table.insert('', 'end', iid=str(idx), values=(hit.agent, str(hit.path), hit.status))
                    if self.findings and self.findings[0].source:
                        self.table.selection_set('0')
                        self.select()
                    state = 'Cancelled' if job.is_set() else 'Complete'
                    self.status.set(f'{state} · {len(self.findings):,} agent folders · {skipped:,} inaccessible directories')
                    return
            except queue.Empty:
                self.timer = self.after(100, poll)
        threading.Thread(target=work, daemon=True).start()
        self.timer = self.after(100, poll)

    def select(self, _event=None):
        selection = self.table.selection()
        enabled = selection and self.findings[int(selection[0])].source
        self.open_button.configure(state='normal' if enabled else 'disabled')

    def open_source(self, _event=None):
        selection = self.table.selection()
        if not selection:
            return
        hit = self.findings[int(selection[0])]
        if hit.source:
            pane = self.app.nametowidget(next(tab for tab in self.app.tabs.tabs()
                                               if self.app.tabs.tab(tab, 'text') == hit.agent))
            self.app.tabs.select(pane)
            pane.scan_source = (hit.source, self.root_path)
            pane.db_path.set(str(hit.source))
            pane._load()
            self.destroy()
