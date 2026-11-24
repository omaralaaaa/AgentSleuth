"""Tkinter window layout, styles and basic scroll behavior."""

import tkinter as tk
from tkinter import ttk
from ..core.search import ALL_ENTRIES





class LayoutMixin:
    BG = '#191b1f'
    PANEL = '#23262b'
    FG = '#dee1e5'
    DIM = '#adb3bc'
    ACCENT = '#99b5d3'
    BORDER = '#454a53'

    def _style(self):
        sty = ttk.Style(self)
        sty.theme_use('clam')
        self.option_add('*TCombobox*Listbox.background', self.PANEL)
        self.option_add('*TCombobox*Listbox.foreground', self.FG)
        sty.configure('.', background=self.PANEL, foreground=self.FG, bordercolor=self.BORDER,
                      lightcolor=self.BORDER, darkcolor=self.BG, arrowcolor=self.ACCENT,
                      font=('Consolas', 10))
        sty.configure('TButton', padding=(10, 5), relief='raised')
        sty.configure('Disclosure.TButton', background='#28313b', foreground=self.ACCENT,
                      padding=(5, 3), relief='flat', borderwidth=0, anchor='w')
        sty.map('TButton', background=[('pressed', self.BORDER), ('active', '#343a42')],
                foreground=[('disabled', self.DIM), ('active', self.FG)])
        sty.configure('Accent.TButton', background=self.ACCENT, foreground=self.BG)
        sty.map('Accent.TButton', background=[('disabled', self.PANEL), ('active', '#adc6de')],
                foreground=[('disabled', self.DIM), ('!disabled', self.BG)])
        sty.configure('TEntry', fieldbackground=self.BG, foreground=self.FG,
                      insertcolor=self.ACCENT, padding=5)
        sty.map('TEntry', fieldbackground=[('readonly', self.BG)])
        sty.configure('TProgressbar', background=self.ACCENT, troughcolor=self.PANEL)
        sty.configure('TCombobox', padding=5)
        sty.map('TCombobox', fieldbackground=[('readonly', self.PANEL)],
                foreground=[('readonly', self.FG)], selectbackground=[('readonly', self.PANEL)],
                selectforeground=[('readonly', self.FG)])
        sty.configure('TScrollbar', background=self.BORDER, troughcolor=self.BG)
        sty.map('TScrollbar', background=[('active', '#59616d')])
        sty.configure('TNotebook', background=self.BG, borderwidth=0)
        sty.configure('TNotebook.Tab', padding=(13, 5))
        sty.map('TNotebook.Tab', background=[('selected', self.ACCENT)],
                foreground=[('selected', self.BG)])
        sty.configure('Conversations.Treeview',
                      background=self.PANEL, fieldbackground=self.PANEL,
                      foreground=self.FG, rowheight=29, borderwidth=0,
                      font=('Consolas', 9))
        sty.configure('Conversations.Treeview.Heading',
                      background=self.BG, foreground=self.DIM,
                      font=('Consolas', 9, 'bold'), relief='flat', padding=(6, 7))
        sty.map('Conversations.Treeview',
                background=[('selected', self.ACCENT)],
                foreground=[('selected', self.BG)])
        sty.map('Conversations.Treeview.Heading',
                background=[('active', self.BORDER)])

    def _label(self, parent, text_value, fg=None, font=None, **kwargs):
        return tk.Label(parent, text=text_value, bg=parent.cget('bg'), fg=fg or self.FG,
                        font=font or ('Consolas', 10), **kwargs)

    def _build_masthead(self):
        top = tk.Frame(self, bg=self.BG, padx=15, pady=10)
        top.pack(fill='x')
        masthead = tk.Frame(top, bg=self.PANEL, padx=12, pady=4)
        masthead.pack(fill='x')
        mark = tk.Canvas(masthead, width=29, height=25, bg=self.PANEL, highlightthickness=0)
        mark.pack(side='left', padx=(0, 10))
        mark.create_rectangle(1, 2, 27, 22, fill=self.BG, outline='')
        mark.create_line(5, 7, 10, 12, 5, 17, fill=self.ACCENT, width=2)
        mark.create_rectangle(13, 15, 21, 17, fill=self.ACCENT, outline='')
        self._label(masthead, 'AGENTSLEUTH', self.FG, ('Consolas', 19, 'bold')).pack(side='left')
        ttk.Button(masthead, text='Scan for artifacts…', command=self.open_scanner).pack(side='right')

    def _build(self):
        top = tk.Frame(self, bg=self.BG, padx=15, pady=10)
        top.pack(fill='x')
        db_row = tk.Frame(top, bg=self.BG)
        db_row.pack(fill='x', pady=(11, 4))
        self._label(db_row, self.parser.source_label, self.DIM).pack(side='left', padx=(0, 9))
        ttk.Entry(db_row, textvariable=self.db_path).pack(side='left', fill='x', expand=True)
        ttk.Button(db_row, text='Browse', command=self._browse_db).pack(side='left', padx=(7, 4))
        self.load_button = ttk.Button(db_row, text='Load conversations', style='Accent.TButton', command=self._load)
        self.load_button.pack(side='left')
        if self.closable:
            ttk.Button(db_row, text='Close tab', command=lambda: self.winfo_toplevel().close_source_tab(self)).pack(
                side='left', padx=(6, 0)
            )
        if self.uses_output_directory:
            out_row = tk.Frame(top, bg=self.BG)
            out_row.pack(fill='x', pady=(4, 4))
            self._label(out_row, 'Export directory:', self.DIM).pack(side='left', padx=(0, 9))
            ttk.Entry(out_row, textvariable=self.output_root, state='readonly').pack(
                side='left', fill='x', expand=True
            )
            ttk.Button(out_row, text='Change folder', command=self._browse_output).pack(side='left', padx=(7, 0))
        status_row = tk.Frame(top, bg=self.BG)
        status_row.pack(fill='x', pady=(4, 0))
        self.progress = ttk.Progressbar(status_row, mode='indeterminate', length=140)
        tk.Label(status_row, textvariable=self.status, bg=self.BG, fg=self.DIM,
                 font=('Consolas', 10), anchor='w').pack(side='left', fill='x', expand=True)

        split = tk.PanedWindow(self, orient='horizontal', bg=self.BORDER, sashwidth=5, borderwidth=0)
        split.pack(fill='both', expand=True, padx=12, pady=(3, 12))
        left = tk.Frame(split, bg=self.PANEL, padx=11, pady=12)
        split.add(left, minsize=205, width=325)
        self._label(left, 'CONVERSATION INDEX', self.DIM, ('Consolas', 12, 'bold')).pack(anchor='w')
        self._label(left, 'Filter conversations', self.DIM).pack(anchor='w', pady=(8, 2))
        ttk.Entry(left, textvariable=self.filter_text).pack(fill='x', pady=(0, 8))
        self._filter_timer = None
        self.filter_text.trace_add('write', self._schedule_filter)
        sidebar_wrap = tk.Frame(left, bg=self.PANEL)
        sidebar_wrap.pack(fill='both', expand=True)
        sidebar_wrap.grid_rowconfigure(0, weight=1)
        sidebar_wrap.grid_columnconfigure(0, weight=1)
        self.sidebar_columns = getattr(self.parser, 'sidebar_columns', ())
        self.conversations = ttk.Treeview(
            sidebar_wrap, columns=('number', 'name', *(key for key, _, _ in self.sidebar_columns)), show='headings',
            selectmode='browse', style='Conversations.Treeview'
        )
        self.conversations.heading('number', text='#', anchor='center')
        self.conversations.heading('name', text='Conversation', anchor='w')
        self.conversations.column('number', width=42, minwidth=42, stretch=False, anchor='center')
        self.conversations.column('name', width=225, minwidth=125, stretch=True, anchor='w')
        for key, label, width in self.sidebar_columns:
            self.conversations.heading(key, text=label, anchor='w')
            self.conversations.column(key, width=width, minwidth=100, stretch=False, anchor='w')
        self.conversations.tag_configure('odd', background=self.PANEL)
        self.conversations.tag_configure('even', background='#282b30')
        sidebar_scroll = ttk.Scrollbar(sidebar_wrap, orient='vertical', command=self.conversations.yview)
        sidebar_hscroll = ttk.Scrollbar(sidebar_wrap, orient='horizontal', command=self.conversations.xview)
        self.conversations.configure(yscrollcommand=sidebar_scroll.set,
                                     xscrollcommand=sidebar_hscroll.set)
        self.conversations.grid(row=0, column=0, sticky='nsew')
        sidebar_scroll.grid(row=0, column=1, sticky='ns')
        sidebar_hscroll.grid(row=1, column=0, sticky='ew')
        self.conversations.bind('<<TreeviewSelect>>', self._select_thread)
        source_prompt = 'No source selected' if self.sidebar_columns else 'No database selected'
        self.sidebar_info = self._label(left, source_prompt, self.DIM,
                                       ('Consolas', 9), justify='left', wraplength=280)
        self.sidebar_info.pack(anchor='w', pady=(10, 0))

        right = tk.Frame(split, bg=self.BG)
        split.add(right, minsize=480)
        header = tk.Frame(right, bg=self.BG, padx=15, pady=10)
        header.pack(fill='x')
        self.thread_title = self._label(header, 'Select a conversation', self.FG,
                                        ('Consolas', 15, 'bold'), anchor='w', justify='left', wraplength=840)
        self.thread_title.pack(fill='x')
        self.thread_cwd = self._label(header, '', self.DIM, ('Consolas', 9),
                                      anchor='w', justify='left', wraplength=840)
        self.thread_cwd.pack(fill='x', pady=(2, 0))
        self.thread_rollout = self._label(header, '', self.DIM, ('Consolas', 9),
                                          anchor='w', justify='left', wraplength=840)
        self.thread_rollout.pack(fill='x', pady=(2, 0))
        nav = tk.Frame(right, bg=self.BG, padx=15, pady=4)
        nav.pack(fill='x')
        self._label(nav, 'View:', self.DIM).pack(side='left', padx=(0, 8))
        self.view_mode = 'Tree'
        self.view_buttons = {}
        for mode in ('Tree', 'Conversation'):
            button = ttk.Button(nav, text=mode, width=len(mode) + 1,
                                style='Accent.TButton' if mode == self.view_mode else 'TButton',
                                command=lambda choice=mode: self._set_view_mode(choice))
            button.pack(side='left')
            self.view_buttons[mode] = button
        self.turn_options = ttk.Combobox(nav, state='readonly', width=18, values=['Entire conversation'])
        self.turn_options.pack(side='left', fill='x', expand=True)
        self.turn_options.current(0)
        self.turn_options.bind('<<ComboboxSelected>>', self._turn_changed)
        self.conversation_stats = self._label(nav, '', self.DIM, ('Consolas', 9))
        self.conversation_stats.pack(side='left', padx=(9, 0))

        filters = tk.Frame(right, bg=self.BG, padx=15)
        filters.pack(fill='x', pady=(0, 5))
        self._label(filters, 'Search:', self.DIM).pack(side='left', padx=(0, 6))
        self.query = tk.StringVar(self)
        self.search_entry = ttk.Entry(filters, textvariable=self.query, width=14)
        self.search_entry.pack(side='left', fill='x', expand=True)
        self.entry_type = tk.StringVar(self, value=ALL_ENTRIES)
        self.filter_options = ttk.Combobox(filters, state='readonly', width=24, values=(ALL_ENTRIES,),
                                          textvariable=self.entry_type)
        self.filter_options.pack(side='left', padx=6)
        def clear_filters():
            self.entry_type.set(ALL_ENTRIES)
            self.query.set('')
        ttk.Button(filters, text='Clear', command=clear_filters).pack(side='left')
        self._search_timer = None
        self.query.trace_add('write', self._schedule_search)
        self.entry_type.trace_add('write', self._schedule_search)

        container = tk.Frame(right, bg=self.BG)
        container.pack(fill='both', expand=True)
        self.conversation_pane = right
        self.canvas = tk.Canvas(container, bg=self.BG, highlightthickness=0)
        scroll = ttk.Scrollbar(container, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        # Keep native windows card-sized. One transcript-height window can be
        # clipped by the Windows window manager far down a long conversation.
        self._rows = []
        self._layout_timer = None
        self._content_height = 0
        self.canvas.bind('<Configure>', self._resize)

        # Put a custom bindtag before Text/Treeview class bindings so the main
        # conversation canvas receives the wheel anywhere inside the pane.
        self._conversation_wheel_tag = f'AgentSleuthConversationWheel{self}'
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
        for item, _ in self._rows:
            self.canvas.itemconfigure(item, width=event.width)
        self._schedule_row_layout()
        for lbl in (self.thread_title, self.thread_cwd, self.thread_rollout):
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
            if isinstance(event.widget, tk.Text):
                first, last = event.widget.yview()
                if (steps < 0 and first > 0) or (steps > 0 and last < 1):
                    event.widget.yview_scroll(steps, 'units')
                    return 'break'
            self.canvas.yview_scroll(steps, 'units')
        except tk.TclError:
            pass
        return 'break'
