"""Render reconstructed messages and correlated execution/activity cards."""

import json
import ntpath
import os
import subprocess
import sys
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from ..core.paths import _path_from_stored
from ..core.utils import safe_text





class ConversationMixin:
    def _render(self, _event=None):
        self._clear_chat()
        if not self.result:
            return
        selection = self.turn_options.current()
        turns = self.result['turns']
        if selection > 0:
            turns = turns[selection - 1:selection]
        total = sum(len(turn['entries']) for turn in turns)
        if not total:
            self._section('No selected events found in this rollout.')
            return

        def entries():
            for turn in turns:
                for index, entry in enumerate(turn['entries']):
                    if index == 0:
                        self._section('Turn · ' + turn['title'])
                    yield entry

        pending = entries()
        rendered = errors = 0
        def append_batch():
            nonlocal rendered, errors
            self._render_timer = None
            for _ in range(min(8, total - rendered)):
                entry = next(pending)
                try:
                    self._render_entry(entry)
                except Exception as exc:
                    ordinal = entry.get('ordinal', '?') if isinstance(entry, dict) else '?'
                    self._render_error_entry(ordinal, exc)
                    errors += 1
                rendered += 1
            status = f'Showing {rendered} of {total} entries'
            self.status.set(status + (f' · {errors} render warnings' if errors else ''))
            if rendered < total:
                self._render_timer = self.after(10, append_batch)

        append_batch()

    def _render_error_entry(self, ordinal, error):
        holder = tk.Frame(self.chat_frame, bg=self.BG)
        holder.pack(fill='x', padx=16, pady=5)
        card = tk.Frame(holder, bg='#30272a', highlightthickness=1, highlightbackground='#70545b')
        card.pack(fill='x')
        self._label(card, f'RENDER WARNING · ordinal {ordinal}', '#e4b5bb',
                    ('Consolas', 9, 'bold')).pack(anchor='w', padx=12, pady=(8, 2))
        self._label(card, safe_text(error), self.FG, ('Consolas', 9),
                    anchor='w', justify='left', wraplength=max(420, self.canvas.winfo_width() - 100)).pack(
                        fill='x', padx=12, pady=(2, 8))

    def _refresh_conversation_scrollregion(self):
        try:
            self.canvas.configure(scrollregion=self.canvas.bbox('all'))
        except tk.TclError:
            pass

    def _body(self, parent, content, bg, max_rows=12, monospace=False):
        """Fit short bodies to their wrapped text and scroll long bodies in place."""
        holder = tk.Frame(parent, bg=bg)
        holder.pack(fill='x', padx=13, pady=(3, 10))
        txt = tk.Text(holder, height=1, width=1, wrap=tk.WORD, bg=bg, fg=self.FG,
                      highlightthickness=0, borderwidth=0, relief='flat',
                      font=('Consolas', 10) if monospace else ('Segoe UI', 10),
                      padx=2, pady=2, spacing1=1, spacing3=1)
        scroll = ttk.Scrollbar(holder, orient='vertical', command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        value = safe_text(content)
        txt.insert('1.0', value)
        txt.configure(state='disabled')
        txt.pack(side='left', fill='x', expand=True)
        logical_overflow = value.count('\n') >= max_rows
        last_width = 0

        def fit(event):
            nonlocal last_width
            if event.width <= 1 or event.width == last_width:
                return
            last_width = event.width
            if logical_overflow:
                rows = max_rows + 1
            else:
                count = txt.count('1.0', 'end-1c', 'displaylines')
                rows = 1 + (count[0] if count else 0)
            txt.configure(height=min(max_rows, rows))
            if rows > max_rows:
                scroll.pack(side='right', fill='y')
            else:
                scroll.pack_forget()

        txt.bind('<Configure>', fit)
        return txt

    def _inner_panel(self, parent, heading, bg='#202328'):
        shell = tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=self.BORDER)
        shell.pack(fill='x', padx=12, pady=(6, 8))
        self._label(shell, heading, self.ACCENT, ('Consolas', 10, 'bold')).pack(anchor='w', padx=12, pady=(9, 2))
        return shell

    def _field(self, panel, label, value, multiline=False):
        if value is None or value == '':
            return
        if not multiline:
            # Compact readable metadata: no two-line Text widget for every field.
            wrap = max(420, self.canvas.winfo_width() - 145)
            line = f'{label}:  {value}'
            self._label(panel, line, self.FG, ('Consolas', 9),
                        anchor='w', justify='left', wraplength=wrap).pack(
                            fill='x', padx=13, pady=(4, 3))
            return
        self._label(panel, label, self.DIM, ('Consolas', 9, 'bold')).pack(
            anchor='w', padx=13, pady=(7, 1))
        self._body(panel, value, panel.cget('bg'), max_rows=9, monospace=True)

    def _render_entry(self, entry):
        kind = entry['kind']
        is_message = kind == 'message'
        user = is_message and entry.get('role') == 'user'
        bg = '#28313b' if user else self.PANEL if is_message else '#25282d'
        holder = tk.Frame(self.chat_frame, bg=self.BG)
        holder.pack(fill='x', padx=(72, 16) if user else (16, 72) if is_message else (16, 16), pady=7)
        card = tk.Frame(holder, bg=bg, highlightthickness=1, highlightbackground=self.BORDER)
        card.pack(fill='x')
        header = tk.Frame(card, bg=bg)
        header.pack(fill='x', padx=13, pady=(10, 2))
        if is_message:
            label = 'YOU' if user else self.parser.name.upper() + (' · ' + entry['phase'] if entry.get('phase') else '')
        else:
            activity_labels = {
                'CommandExecution': 'EXECUTION · COMMAND',
                'FileChange': 'EXECUTION · FILE CHANGE',
                'McpToolCall': 'EXECUTION · MCP TOOL',
                'DynamicToolCall': 'EXECUTION · DYNAMIC TOOL',
                'CollabAgentToolCall': 'EXECUTION · COLLAB AGENT',
            }
            label = activity_labels.get(
                entry.get('activity_type'),
                'ACTIVITY · ' + entry.get('activity_type', 'UNKNOWN')
            )
        self._label(header, label, self.ACCENT if is_message else self.DIM,
                    ('Consolas', 10, 'bold')).pack(side='left')
        meta = f'#{entry["ordinal"]}  ·  {entry.get("timestamp", "")[:19].replace("T", " ")} UTC'
        self._label(header, meta, self.DIM, ('Consolas', 8)).pack(side='right')
        if is_message:
            self._body(card, entry.get('text', ''), bg)
            self._file_links(card, entry.get('file_refs', []), entry.get('attachments', []))
        else:
            self._render_activity(card, entry)
        self._bind_conversation_wheel_tree(holder)

    def _render_activity(self, card, entry):
        headings = {
            'CommandExecution': 'COMMAND DETAILS',
            'FileChange': 'FILE CHANGE DETAILS',
            'McpToolCall': 'MCP TOOL DETAILS',
            'DynamicToolCall': 'DYNAMIC TOOL DETAILS',
            'CollabAgentToolCall': 'COLLAB AGENT DETAILS',
        }
        panel = self._inner_panel(
            card, headings.get(entry.get('activity_type'), 'ACTIVITY DETAILS')
        )
        self._render_activity_fields(panel, entry)

    def _render_activity_fields(self, panel, activity):
        kind = activity['activity_type']
        self._field(panel, 'Status', activity.get('status'))
        if kind == 'CommandExecution':
            self._field(panel, 'Process ID', activity.get('pid'))
            self._field(panel, 'Working directory', activity.get('cwd'))
            self._field(panel, 'Exit code', activity.get('exit_code'))
            self._field(panel, 'Shell command', activity.get('command'), multiline=True)
            output = activity.get('item', {}).get('aggregated_output')
            if output:
                self._field(panel, 'Command stdout/stderr (aggregated)', output, multiline=True)
        elif kind == 'FileChange':
            item = activity.get('item') or {}
            for filename, change in (item.get('changes') or {}).items():
                operation = (change or {}).get('type', 'change')
                basename = ntpath.basename(str(filename).replace('/', '\\')) or str(filename)
                recovered = None
                if self.result:
                    recovered = next((r for r in self.result.get('recovered_files', [])
                                      if r['ordinal'] == activity['ordinal']
                                      and r['original_path'] == filename), None)
                if recovered:
                    self._filename_link(
                        panel, basename, Path(recovered['saved_path']),
                        suffix=f'[{operation}] · rebuilt copy'
                    )
                else:
                    self._field(panel, 'File', f'{basename}  [{operation}] · no rebuilt copy recorded')
                if change and change.get('content'):
                    self._field(panel, 'Recorded file content', change['content'], multiline=True)
            self._field(panel, 'stdout', item.get('stdout'), multiline=True)
            self._field(panel, 'stderr', item.get('stderr'), multiline=True)
        else:
            item = activity.get('item') or {}
            for name in ('server', 'tool', 'name', 'arguments', 'result', 'error'):
                if name in item:
                    value = item[name]
                    if isinstance(value, (list, dict)):
                        value = json.dumps(value, indent=2, ensure_ascii=False)
                    self._field(panel, name.capitalize(), value, multiline=name in {'arguments', 'result'})
        self._field(panel, 'Correlation', activity.get('correlation_note'))
        self._file_links(panel, [], activity.get('attachments', []))

    def _filename_link(self, parent, filename, target=None, suffix=''):
        """Render a filename only; links always target a rebuilt/extracted copy."""
        row = tk.Frame(parent, bg=parent.cget('bg'))
        row.pack(fill='x', padx=15, pady=(4, 3))
        label_text = str(filename or 'Attachment')
        if suffix:
            label_text += f'  {suffix}'
        exists = bool(target and Path(target).is_file())
        label = self._label(
            row, label_text, self.ACCENT if exists else self.FG,
            ('Consolas', 9, 'underline') if exists else ('Consolas', 9),
            cursor='hand2' if exists else 'arrow', anchor='w'
        )
        label.pack(anchor='w')
        if exists:
            label.bind('<Button-1>', lambda _e, path=Path(target): self._reveal_path(path))

    def _file_links(self, parent, file_refs, attachments):
        """Show filename-only links to extracted copies, never original source paths."""
        extracted = [a for a in attachments
                     if a.get('status') == 'extracted' and a.get('filename')]
        output_dir = Path(self.result['output_directory']) if self.result else None
        attachment_dir = output_dir / 'attachments' if output_dir else None
        used_ids = set()

        # Pair source marker names with decoded attachments by their order in
        # this message. The link target is always AgentSleuth's extracted copy,
        # never the historical path recorded by Codex.
        for index, ref in enumerate(file_refs or []):
            fallback = extracted[index] if index < len(extracted) else None
            target = (attachment_dir / fallback['filename']) if fallback and attachment_dir else None
            if fallback:
                used_ids.add(fallback.get('attachment_id'))
            self._filename_link(
                parent,
                ref.get('filename') or (fallback or {}).get('filename') or 'Attachment',
                target,
                suffix='· extracted copy' if target and target.is_file() else ''
            )

        # Attachments without a visible source-path marker use their extracted name.
        for attachment in extracted:
            if attachment.get('attachment_id') in used_ids:
                continue
            target = attachment_dir / attachment['filename'] if attachment_dir else None
            self._filename_link(parent, attachment['filename'], target, suffix='· extracted copy')

    def _reveal_path(self, raw_path):
        """Navigate to a file in the OS file manager; never launch the file itself."""
        try:
            path = raw_path if isinstance(raw_path, Path) else _path_from_stored(str(raw_path))
            path = path.expanduser()
            if not path.exists():
                messagebox.showwarning(
                    'File path unavailable',
                    'The recorded file path is not accessible on this machine.\n\n'
                    f'{path}\n\nThe file was not opened or executed.'
                )
                return
            if sys.platform == 'win32':
                if path.is_dir():
                    os.startfile(str(path))
                else:
                    subprocess.Popen(['explorer.exe', f'/select,{path}'])
            elif sys.platform == 'darwin':
                if path.is_dir():
                    subprocess.Popen(['open', str(path)])
                else:
                    subprocess.Popen(['open', '-R', str(path)])
            else:
                # Linux file managers open the containing directory; no file handler is invoked.
                directory = path if path.is_dir() else path.parent
                subprocess.Popen(['xdg-open', str(directory)])
        except Exception as exc:
            messagebox.showerror('Show file location', str(exc))
