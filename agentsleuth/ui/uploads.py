"""Export controls for a selected conversation and its recorded prompt uploads."""

import tkinter as tk
from tkinter import ttk

from ..core.utils import short
from ..core.upload_listing import prompt_uploads




class UploadDialog(tk.Toplevel):
    def __init__(self, pane, directory):
        super().__init__(pane)
        self.title('Uploads by prompt')
        self.geometry('880x520')
        self.minsize(530, 350)
        self.configure(bg=pane.BG)
        self.transient(pane.winfo_toplevel())
        self.bind('<Escape>', lambda event: self.destroy())

        frame = ttk.Frame(self, padding=10)
        frame.pack(fill='both', expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(frame, columns=('status', 'copy'), selectmode='browse',
                                 style='Conversations.Treeview')
        for column, label, width in (('#0', 'Prompt / uploaded file', 450),
                                     ('status', 'Status', 110), ('copy', 'Exported filename', 265)):
            self.tree.heading(column, text=label, anchor='w')
            self.tree.column(column, width=width, minwidth=width, stretch=column == '#0')
        vertical = ttk.Scrollbar(frame, command=self.tree.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        self.prompt_text = tk.Text(frame, height=6, width=1, wrap='word', bg=pane.BG,
                                   fg=pane.FG, state='disabled', padx=8, pady=6)
        self.prompt_text.grid(row=2, column=0, sticky='ew', pady=(8, 0))
        prompt_scroll = ttk.Scrollbar(frame, command=self.prompt_text.yview)
        prompt_scroll.grid(row=2, column=1, sticky='ns', pady=(8, 0))
        self.prompt_text.configure(yscrollcommand=prompt_scroll.set)
        self.prompts = {}
        self.files = {}
        for turn, ordinal, text, files in prompt_uploads(pane.result, directory):
            heading = f'Turn {turn} · #{ordinal} · {short(" ".join(text.split()), 120)}'
            row = self.tree.insert('', 'end', text=heading, open=True)
            self.prompts[row] = text
            for filename, target, status in files:
                child = self.tree.insert(row, 'end', text=filename,
                                         values=(status, target.name if target else ''))
                if target:
                    self.files[child] = target

        footer = ttk.Frame(frame)
        footer.grid(row=3, column=0, sticky='ew', pady=(8, 0))
        self.show_file = ttk.Button(footer, text='Show file in folder', state='disabled',
                                    command=lambda: self._reveal_selected(pane))
        self.show_file.pack(side='left')
        ttk.Button(footer, text='Close', command=self.destroy).pack(side='right')
        self.tree.bind('<<TreeviewSelect>>', self._select)
        self.tree.bind('<Double-1>', lambda event: self._reveal_selected(pane))
        if self.prompts:
            first = next(iter(self.prompts))
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._select()
        else:
            self._show_prompt('No uploaded files are linked to prompts in this conversation.')
        self.tree.focus_set()

    def _select(self, _event=None):
        row = next(iter(self.tree.selection()), '')
        prompt = self.tree.parent(row) if row else ''
        self._show_prompt(self.prompts.get(prompt or row, ''))
        self.show_file.configure(state='normal' if row in self.files else 'disabled')

    def _show_prompt(self, text):
        self.prompt_text.configure(state='normal')
        self.prompt_text.delete('1.0', 'end')
        self.prompt_text.insert('1.0', text.encode('utf-8', errors='backslashreplace').decode('utf-8'))
        self.prompt_text.configure(state='disabled')

    def _reveal_selected(self, pane):
        if target := self.files.get(next(iter(self.tree.selection()), '')):
            pane._reveal_path(target)
