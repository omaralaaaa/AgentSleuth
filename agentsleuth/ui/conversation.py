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
from .powershell import insert_command, is_powershell





class ConversationMixin:
    def _schedule_search(self, *_):
        if self._search_timer is not None:
            self.after_cancel(self._search_timer)
        def apply():
            self._search_timer = None
            if self.result and not self._working:
                self._render()
        self._search_timer = self.after(120, apply)

    def _render(self, _event=None, *, keep_position=False):
        if not self.result:
            return
        if self._render_timer is not None:
            self.after_cancel(self._render_timer)
            self._render_timer = None
        selection = self.turn_options.current()
        matches = self._index.matches(self.query.get(), self.entry_type.get(),
                                      selection - 1 if selection > 0 else None)
        requested = []
        previous = None
        current_prompt = None
        total = 0
        hidden = 0
        for turn, _, entry in matches:
            if turn != previous:
                requested.append((('turn', turn), f'Turn {turn + 1}'))
                previous = turn
                current_prompt = None
            total += 1
            prompt = self._index.prompt_for.get(id(entry))
            if prompt is not None:
                if current_prompt != id(prompt):
                    requested.append((id(prompt), prompt))
                    current_prompt = id(prompt)
                if current_prompt in self._collapsed_prompts:
                    hidden += 1
                    continue
            elif entry.get('role') == 'user':
                current_prompt = id(entry)
            requested.append((id(entry), entry))
        if not requested:
            requested.append(('empty', 'No matching entries in this view.'))
        wanted = {key for key, _ in requested}
        for key, (item, row) in self._row_cache.items():
            if key not in wanted and row._shown:
                self.canvas.itemconfigure(item, state='hidden')
                row._shown = False
        self._rows.clear()
        if not keep_position:
            self.canvas.yview_moveto(0)
        pending = iter(requested)
        processed = errors = 0
        def append_batch():
            nonlocal processed, errors
            self._render_timer = None
            created = 0
            while processed < len(requested) and created < 8:
                key, value = next(pending)
                processed += 1
                if key in self._row_cache:
                    item, row = self._row_cache[key]
                    if not row._shown:
                        self.canvas.itemconfigure(item, state='normal', width=self.canvas.winfo_width())
                        row._shown = True
                    self._rows.append((item, row))
                    continue
                if isinstance(value, str):
                    self._section(value)
                else:
                    try:
                        self._render_entry(value)
                    except Exception as exc:
                        self._render_error_entry(value.get('ordinal', '?'), exc)
                        errors += 1
                item, row = self._rows[-1]
                row._shown = True
                self._row_cache[key] = item, row
                created += 1
            self._schedule_row_layout()
            status = f'{total} matching entries'
            if hidden:
                status += f' · {hidden} collapsed'
            if not self._working:
                self.status.set(status + (f' · {errors} render warnings' if errors else ''))
            if processed < len(requested):
                self._render_timer = self.after(10, append_batch)
            elif created:
                # Unmapped cards can finish requesting their heights without
                # receiving a Configure event. Measure after Tk settles geometry.
                self.update_idletasks()
                self._schedule_row_layout()

        append_batch()

    def _render_error_entry(self, ordinal, error):
        holder = tk.Frame(self._new_row(), bg=self.BG)
        holder.pack(fill='x', padx=16, pady=5)
        card = tk.Frame(holder, bg='#30272a', highlightthickness=1, highlightbackground='#70545b')
        card.pack(fill='x')
        self._label(card, f'RENDER WARNING · ordinal {ordinal}', '#e4b5bb',
                    ('Consolas', 9, 'bold')).pack(anchor='w', padx=12, pady=(8, 2))
        self._label(card, safe_text(error), self.FG, ('Consolas', 9),
                    anchor='w', justify='left', wraplength=max(420, self.canvas.winfo_width() - 100)).pack(
                        fill='x', padx=12, pady=(2, 8))

    def _new_row(self):
        row = tk.Frame(self.canvas, bg=self.BG)
        item = self.canvas.create_window(0, self._content_height, anchor='nw',
                                         width=max(1, self.canvas.winfo_width()), window=row)
        self._rows.append((item, row))
        row.bind('<Configure>', self._schedule_row_layout)
        self._schedule_row_layout()
        return row

    def _schedule_row_layout(self, _event=None):
        if self._layout_timer is None:
            self._layout_timer = self.after_idle(self._layout_rows)

    def _layout_rows(self):
        self._layout_timer = None
        first, last = self.canvas.yview()
        at_bottom = first > 0 and last >= 1
        y = 0
        for item, row in self._rows:
            if getattr(row, '_layout_y', None) != y:
                self.canvas.coords(item, 0, y)
                row._layout_y = y
            y += row.winfo_reqheight()
        self._content_height = y
        self.canvas.configure(scrollregion=(0, 0, self.canvas.winfo_width(), y))
        if at_bottom:
            self.canvas.yview_moveto(1)

    def _body(self, parent, content, bg, max_rows=12, monospace=False, powershell=False):
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
        if not value.isascii():
            value = value.encode('utf-8', errors='backslashreplace').decode('utf-8')
        if powershell:
            insert_command(txt, value)
        else:
            txt.insert('1.0', value)
        logical_rows = value.count('\n') + 1
        txt.configure(state='disabled', height=min(logical_rows, max_rows))
        txt.pack(side='left', fill='x', expand=True)
        logical_overflow = logical_rows > max_rows
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

    def _field(self, panel, label, value, multiline=False, powershell=False, show_empty=False):
        if value is None or (value == '' and not show_empty):
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
        self._body(panel, value, panel.cget('bg'), max_rows=9, monospace=True, powershell=powershell)

    def _render_entry(self, entry):
        kind = entry['kind']
        is_message = kind == 'message'
        user = is_message and entry.get('role') == 'user'
        bg = '#28313b' if user else self.PANEL if is_message else '#25282d'
        nested = id(entry) in self._index.prompt_for
        holder = tk.Frame(self._new_row(), bg=self.BG)
        holder.pack(fill='x', padx=(16, 16), pady=(8 if user else 0, 0))
        if nested:
            guide = tk.Frame(holder, bg=self.BG, width=24)
            guide.pack(side='left', fill='y')
            guide_color = '#566677'
            tk.Frame(guide, bg=guide_color).place(x=10, y=0, width=2, relheight=1)
            tk.Frame(guide, bg=guide_color).place(x=11, y=17, width=13, height=2)
        card = tk.Frame(holder, bg=bg, highlightthickness=int(user), highlightbackground=self.BORDER)
        card.pack(fill='x', expand=True, pady=(0 if user else 3, 0))
        header = tk.Frame(card, bg=bg)
        header.pack(fill='x', padx=13, pady=(10, 2))
        if entry.get('agent') == 'opencode' and entry.get('event_type') == 'assistant_error':
            label = 'ASSISTANT ERROR'
        elif is_message:
            label = 'USER' if user else self.parser.name.upper() + (' · ' + entry['phase'] if entry.get('phase') else '')
        else:
            activity_labels = {
                'CommandExecution': 'EXECUTION · COMMAND',
                'FileChange': 'EXECUTION · FILE CHANGE',
                'McpToolCall': 'EXECUTION · MCP TOOL',
                'DynamicToolCall': 'EXECUTION · DYNAMIC TOOL',
                'CollabAgentToolCall': 'EXECUTION · COLLAB AGENT',
                'ToolExecution': 'EXECUTION · TOOL',
                'reasoning': 'RECORDED REASONING',
                'file_attachment': 'FILE ATTACHMENT REFERENCE',
                'file_change': 'FILE CHANGE ARTIFACT',
                'raw_part': 'PART EVIDENCE',
                'raw_message': 'MESSAGE EVIDENCE',
            }
            label = activity_labels.get(
                entry.get('activity_type'),
                'ACTIVITY · ' + entry.get('activity_type', 'UNKNOWN')
            )
        self._label(header, label, self.ACCENT if is_message else self.DIM,
                    ('Consolas', 10, 'bold')).pack(side='left')
        if 'timestamp_label' in entry:
            timestamp = entry['timestamp_label']
        else:
            recorded = entry.get('timestamp') or ''
            timestamp = recorded[:19].replace('T', ' ') + ' UTC' if recorded else ''
        meta = f'#{entry["ordinal"]}' + (f'  ·  {timestamp}' if timestamp else '')
        self._label(header, meta, self.DIM, ('Consolas', 8)).pack(side='right')
        key = id(entry)
        count = self._index.response_counts.get(key, 0)
        if user and 'permissions' in entry:
            self._label(card, 'Permissions: ' + entry['permissions'], self.DIM, ('Consolas', 9),
                        anchor='w', justify='left', wraplength=max(300, self.canvas.winfo_width() - 100)
                        ).pack(fill='x', padx=13, pady=(2, 4))
        if is_message:
            self._body(card, entry.get('text', ''), bg)
            self._file_links(card, entry.get('file_refs', []), entry.get('attachments', []))
        elif 'execution' in entry:
            self._render_execution(card, entry)
        elif 'part_type' in entry:
            self._field(card, 'Part type', entry.get('part_type'))
            if 'text' in entry:
                self._body(card, entry['text'], bg)
            else:
                self._field(card, 'Recorded evidence', entry['evidence'], multiline=True, show_empty=True)
        else:
            self._render_activity_fields(card, entry)
        if user and count:
            def caption():
                marker = '▸' if key in self._collapsed_prompts else '▾'
                noun = 'response' if count == 1 else 'responses'
                return f'{marker}  {count} {noun}'

            def toggle():
                if key in self._collapsed_prompts:
                    self._collapsed_prompts.remove(key)
                else:
                    self._collapsed_prompts.add(key)
                button.configure(text=caption())
                self._render(keep_position=True)

            button = ttk.Button(card, text=caption(), command=toggle, style='Disclosure.TButton')
            button.pack(anchor='w', padx=8, pady=(0, 4))
        self._bind_conversation_wheel_tree(holder)

    def _render_execution(self, panel, entry):
        execution = entry['execution']
        self._field(panel, 'Tool', execution['tool'])
        self._field(panel, 'Input', execution['arguments'], multiline=True, show_empty=True)
        if execution['partial_input'] != execution['arguments']:
            self._field(panel, 'Recorded partial input', execution['partial_input'], multiline=True)
        self._field(panel, 'Recorded output', execution['output'], multiline=True, show_empty=True)
        self._field(panel, 'Recorded error', execution['error'], multiline=True, show_empty=True)
        status = execution['status']
        self._field(panel, 'Status', status if status is not None else 'Not recorded')
        self._field(panel, 'Started', execution['start_label'])
        self._field(panel, 'Ended', execution['end_label'])
        self._field(panel, 'Metadata', execution['metadata'], multiline=True, show_empty=True)

    def _render_activity_fields(self, panel, activity):
        kind = activity['activity_type']
        self._field(panel, 'Status', activity.get('status'))
        if kind == 'CommandExecution':
            self._field(panel, 'Process ID', activity.get('pid'))
            self._field(panel, 'Working directory', activity.get('cwd'))
            self._field(panel, 'Exit code', activity.get('exit_code'))
            command = activity.get('command')
            argv = (activity.get('item') or {}).get('command')
            self._field(panel, 'Shell command', command, multiline=True,
                        powershell=is_powershell(argv, safe_text(command)))
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
        output_dir = (self.result or {}).get('output_directory')
        attachment_dir = Path(output_dir) / 'attachments' if output_dir else None
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
