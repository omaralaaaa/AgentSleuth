"""Tkinter window layout, styles and basic scroll behavior."""

import tkinter as tk
from tkinter import ttk





class LayoutMixin:
    def _style(self):
        sty = ttk.Style(self)
        sty.theme_use('clam')
        sty.configure('Accent.TButton', background=self.ACCENT, foreground='#0e1c21', padding=8)
        sty.map('Accent.TButton', background=[('active', '#82f3d2')])
        sty.configure('TButton', padding=7)
        sty.configure('TEntry', fieldbackground='#f5faff', foreground='#102033', padding=5)
        sty.configure('TProgressbar', background=self.ACCENT, troughcolor=self.PANEL)
        sty.configure('TCombobox', fieldbackground='#ffffff', padding=5)
        sty.configure('Conversations.Treeview',
                      background=self.PANEL, fieldbackground=self.PANEL,
                      foreground=self.FG, rowheight=29, borderwidth=0,
                      font=('Segoe UI', 9))
        sty.configure('Conversations.Treeview.Heading',
                      background='#1c2b42', foreground=self.DIM,
                      font=('Segoe UI', 9, 'bold'), relief='flat', padding=(6, 7))
        sty.map('Conversations.Treeview',
                background=[('selected', '#206d5e')],
                foreground=[('selected', '#ffffff')])
        sty.map('Conversations.Treeview.Heading',
                background=[('active', '#263b58')])

    def _label(self, parent, text_value, fg=None, font=None, **kwargs):
        return tk.Label(parent, text=text_value, bg=parent.cget('bg'), fg=fg or self.FG,
                        font=font or ('Segoe UI', 10), **kwargs)

    def _build(self):
        top = tk.Frame(self, bg=self.BG, padx=15, pady=10)
        top.pack(fill='x')
        self._label(top, 'AGENTSLEUTH', self.ACCENT, ('Segoe UI', 21, 'bold')).pack(anchor='w')
        self._label(top, 'Native Codex conversations reconstructed from SQLite threads + rollout events',
                    self.DIM, ('Segoe UI', 9)).pack(anchor='w')
        db_row = tk.Frame(top, bg=self.BG)
        db_row.pack(fill='x', pady=(11, 4))
        self._label(db_row, 'State database:', self.DIM).pack(side='left', padx=(0, 9))
        ttk.Entry(db_row, textvariable=self.db_path).pack(side='left', fill='x', expand=True)
        ttk.Button(db_row, text='Browse', command=self._browse_db).pack(side='left', padx=(7, 4))
        self.load_button = ttk.Button(db_row, text='Load conversations', style='Accent.TButton', command=self._load)
        self.load_button.pack(side='left')
        out_row = tk.Frame(top, bg=self.BG)
        out_row.pack(fill='x', pady=(4, 4))
        self._label(out_row, 'Extracted files:', self.DIM).pack(side='left', padx=(0, 9))
        ttk.Entry(out_row, textvariable=self.output_root).pack(side='left', fill='x', expand=True)
        ttk.Button(out_row, text='Change folder', command=self._browse_output).pack(side='left', padx=(7, 0))
        self.progress = ttk.Progressbar(top, mode='indeterminate')
        self.progress.pack(fill='x', pady=(6, 2))
        tk.Label(top, textvariable=self.status, bg=self.BG, fg=self.DIM,
                 font=('Segoe UI', 9), anchor='w').pack(fill='x', pady=(3, 0))

        split = tk.PanedWindow(self, orient='horizontal', bg=self.BORDER, sashwidth=5, borderwidth=0)
        split.pack(fill='both', expand=True, padx=12, pady=(3, 12))
        left = tk.Frame(split, bg=self.PANEL, padx=11, pady=12)
        split.add(left, minsize=205, width=325)
        self._label(left, 'CONVERSATIONS', self.FG, ('Segoe UI', 11, 'bold')).pack(anchor='w', pady=(0, 9))
        ttk.Entry(left, textvariable=self.filter_text).pack(fill='x', pady=(0, 8))
        self._filter_timer = None
        self.filter_text.trace_add('write', self._schedule_filter)
        sidebar_wrap = tk.Frame(left, bg=self.PANEL)
        sidebar_wrap.pack(fill='both', expand=True)
        sidebar_wrap.grid_rowconfigure(0, weight=1)
        sidebar_wrap.grid_columnconfigure(0, weight=1)
        self.conversations = ttk.Treeview(
            sidebar_wrap, columns=('number', 'name'), show='headings',
            selectmode='browse', style='Conversations.Treeview'
        )
        self.conversations.heading('number', text='#', anchor='center')
        self.conversations.heading('name', text='Conversation', anchor='w')
        self.conversations.column('number', width=42, minwidth=42, stretch=False, anchor='center')
        self.conversations.column('name', width=225, minwidth=125, stretch=True, anchor='w')
        self.conversations.tag_configure('odd', background='#142034')
        self.conversations.tag_configure('even', background='#18263b')
        sidebar_scroll = ttk.Scrollbar(sidebar_wrap, orient='vertical', command=self.conversations.yview)
        sidebar_hscroll = ttk.Scrollbar(sidebar_wrap, orient='horizontal', command=self.conversations.xview)
        self.conversations.configure(yscrollcommand=sidebar_scroll.set,
                                     xscrollcommand=sidebar_hscroll.set)
        self.conversations.grid(row=0, column=0, sticky='nsew')
        sidebar_scroll.grid(row=0, column=1, sticky='ns')
        sidebar_hscroll.grid(row=1, column=0, sticky='ew')
        self.conversations.bind('<<TreeviewSelect>>', self._select_thread)
        self.sidebar_info = self._label(left, 'No database selected', self.DIM,
                                       ('Segoe UI', 9), justify='left', wraplength=280)
        self.sidebar_info.pack(anchor='w', pady=(10, 0))

        right = tk.Frame(split, bg=self.BG)
        split.add(right, minsize=480)
        header = tk.Frame(right, bg=self.BG, padx=15, pady=10)
        header.pack(fill='x')
        self.thread_title = self._label(header, 'Select a conversation', self.FG,
                                        ('Segoe UI', 15, 'bold'), anchor='w', justify='left', wraplength=840)
        self.thread_title.pack(fill='x')
        self.thread_permissions = self._label(header, '', self.ACCENT, ('Segoe UI', 10),
                                             anchor='w', justify='left', wraplength=840)
        self.thread_permissions.pack(fill='x', pady=(4, 0))
        self.thread_cwd = self._label(header, '', self.DIM, ('Segoe UI', 9),
                                      anchor='w', justify='left', wraplength=840)
        self.thread_cwd.pack(fill='x', pady=(2, 0))
        self.thread_rollout = self._label(header, '', self.DIM, ('Segoe UI', 9),
                                          anchor='w', justify='left', wraplength=840)
        self.thread_rollout.pack(fill='x', pady=(2, 0))
        nav = tk.Frame(right, bg=self.BG, padx=15, pady=4)
        nav.pack(fill='x')
        self._label(nav, 'View:', self.DIM).pack(side='left', padx=(0, 8))
        self.turn_options = ttk.Combobox(nav, state='readonly', width=60, values=['Entire conversation'])
        self.turn_options.pack(side='left', fill='x', expand=True)
        self.turn_options.current(0)
        self.turn_options.bind('<<ComboboxSelected>>', self._render)
        self.conversation_stats = self._label(nav, '', self.DIM, ('Segoe UI', 9))
        self.conversation_stats.pack(side='left', padx=(9, 0))

        container = tk.Frame(right, bg=self.BG)
        container.pack(fill='both', expand=True)
        self.conversation_pane = right
        self.canvas = tk.Canvas(container, bg=self.BG, highlightthickness=0)
        scroll = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.chat_frame = tk.Frame(self.canvas, bg=self.BG)
        self.window_id = self.canvas.create_window((0, 0), anchor='nw', window=self.chat_frame)
        self.chat_frame.bind('<Configure>', lambda _: self._refresh_conversation_scrollregion())
        self.canvas.bind('<Configure>', self._resize)
        self.canvas.bind('<Configure>', lambda _e: self.after_idle(self._refresh_conversation_scrollregion), add='+')

        # Put a custom bindtag before Text/Treeview class bindings so the main
        # conversation canvas receives the wheel anywhere inside the pane.
        self._conversation_wheel_tag = 'AgentSleuthConversationWheel'
        self.bind_class(self._conversation_wheel_tag, '<MouseWheel>', self._on_conversation_wheel)
        self.bind_class(self._conversation_wheel_tag, '<Button-4>', lambda e: self._on_conversation_wheel(e, -1))
        self.bind_class(self._conversation_wheel_tag, '<Button-5>', lambda e: self._on_conversation_wheel(e, 1))
        self._bind_conversation_wheel_tree(right)

    def _schedule_filter(self, *_):
        if self._filter_timer is not None:
            self.after_cancel(self._filter_timer)
        def apply_filter():
            self._filter_timer = None
            self._populate_threads()
        self._filter_timer = self.after(150, apply_filter)

    def _resize(self, event):
        self.canvas.itemconfigure(self.window_id, width=event.width)
        for lbl in (self.thread_title, self.thread_permissions, self.thread_cwd, self.thread_rollout):
            lbl.configure(wraplength=max(420, event.width - 55))

    def _bind_conversation_wheel_tree(self, root):
        """Attach the conversation-wheel tag to all current descendants."""
        tag = getattr(self, '_conversation_wheel_tag', None)
        if not tag:
            return
        pending = [root]
        while pending:
            widget = pending.pop()
            tags = widget.bindtags()
            if tag not in tags:
                widget.bindtags((tag,) + tuple(tags))
            try:
                pending.extend(widget.winfo_children())
            except tk.TclError:
                pass

    def _on_conversation_wheel(self, event, linux_direction=None):
        """Scroll the conversation when the pointer is anywhere in its pane."""
        if linux_direction is not None:
            steps = linux_direction * 3
        else:
            delta = getattr(event, 'delta', 0) or 0
            if not delta:
                return 'break'
            steps = -int(delta / 120)
            # High-resolution wheels may report smaller deltas than 120.
            if steps == 0:
                steps = -1 if delta > 0 else 1
        try:
            self.canvas.yview_scroll(steps, 'units')
        except tk.TclError:
            pass
        # Prevent nested Text widgets from consuming the event themselves.
        return 'break'
