"""Render reconstructed messages and correlated execution/activity cards."""

import json
from bisect import bisect_right
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
    PAGE_SIZE = 20

    def _render(self, _event=None, *, page=0):
        self._clear_chat()
        if not self.result:
            return
        selection = self.turn_options.current()
        turns = self.result['turns']
        base = self._turn_ends[selection - 2] if selection > 1 else 0
        end = self._turn_ends[selection - 1 if selection > 0 else -1] if turns else 0
        if end == base:
            self._section('No selected events found in this rollout.')
            return

        start = base + page * self.PAGE_SIZE
        stop = min(start + self.PAGE_SIZE, end)
        if end - base > self.PAGE_SIZE:
            nav = ttk.Frame(self.chat_frame)
            nav.pack(fill='x', padx=16, pady=6)
            for title, target, enabled in [('Previous', page - 1, start > base),
                                            ('Next', page + 1, stop < end)]:
                ttk.Button(nav, text=title, state='normal' if enabled else 'disabled',
                           command=lambda p=target: self._render(page=p)).pack(side='left')
            ttk.Label(nav, text=f'Entries {start-base+1}–{stop-base} of {end-base}').pack(side='left')
        expected_entries = stop - start
        rendered_entries = 0
        render_errors = []
        for index in range(bisect_right(self._turn_ends, start), len(turns)):
            turn = turns[index]
            offset = self._turn_ends[index - 1] if index else 0
            if offset >= stop:
                break
            self._section('Turn · ' + turn['title'])
            for entry in turn['entries'][max(0, start-offset):stop-offset]:
                try:
                    self._render_entry(entry)
                    rendered_entries += 1
                except Exception as exc:
                    # One malformed/unknown record must not stop the rest of the
                    # conversation from rendering. Keep its ordinal visible.
                    ordinal = entry.get('ordinal', '?') if isinstance(entry, dict) else '?'
                    render_errors.append((ordinal, str(exc)))
                    self._render_error_entry(ordinal, exc)

        self._refresh_conversation_scrollregion()
        self._bind_conversation_wheel_tree(self.conversation_pane)
        self.canvas.yview_moveto(0)
        if render_errors:
            self.status.set(
                f'Rendered {rendered_entries}/{expected_entries} entries · '
                f'{len(render_errors)} item(s) shown with rendering errors'
            )
        else:
            self.status.set(f'Showing entries {start-base+1}–{stop-base} of {end-base}')

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

    def _body(self, parent, content, bg, max_rows=None, monospace=False):
        """Render the complete body; the outer conversation canvas owns scrolling.

        Earlier versions capped Text widgets at a fixed number of rows and added
        nested scrollbars. That made long tool outputs look like missing messages.
        Now every line is included in the card and long lines wrap to the card width.
        """
        value = safe_text(content)
        holder = tk.Frame(parent, bg=bg)
        holder.pack(fill='x', padx=13, pady=(3, 10))

        # Start compact, then ask Tk for the real number of display lines after
        # the widget has its final width. This avoids both clipped long output
        # and the large blank gaps caused by estimating wraps for nowrap text.
        txt = tk.Text(holder, height=1, wrap=tk.WORD, bg=bg, fg=self.FG,
                      insertbackground=self.FG, highlightthickness=0, borderwidth=0,
                      font=('Consolas', 10) if monospace else ('Segoe UI', 10),
                      padx=2, pady=2, relief='flat',
                      spacing1=1, spacing3=1)
        preview = value[:2400]
        preview = '\n'.join(preview.split('\n')[:16])
        txt.insert('1.0', preview)
        txt.configure(state='disabled')
        txt.pack(fill='x', expand=True)

        last_width = {'value': 0}
        scheduled = {'value': False}

        def fit_to_content(_event=None):
            if not txt.winfo_exists():
                return
            width = txt.winfo_width()
            if width <= 2 or width == last_width['value'] or scheduled['value']:
                return
            last_width['value'] = width
            scheduled['value'] = True

            def apply_height():
                scheduled['value'] = False
                try:
                    if not txt.winfo_exists():
                        return
                    measured = txt.count('1.0', 'end-1c', 'displaylines')
                    # count returns display-line transitions, excluding the final row.
                    txt.configure(height=1 + (int(measured[0]) if measured else 0))
                except (tk.TclError, TypeError, ValueError):
                    # Keep the complete text available even if a platform's Tk
                    # build does not support display-line counting.
                    pass

            self.after_idle(apply_height)

        txt.bind('<Configure>', fit_to_content, add='+')
        self.after_idle(fit_to_content)
        if len(preview) < len(value):
            def expand():
                txt.configure(state='normal')
                txt.insert('end-1c', value[len(preview):])
                txt.configure(state='disabled')
                button.destroy()
                last_width['value'] = 0
                fit_to_content()
            button = ttk.Button(holder, text='Show full text', command=expand)
            button.pack(anchor='w')
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
        self._body(panel, value, panel.cget('bg'), max_rows=22, monospace=True)

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
            self._body(card, entry.get('text', ''), bg, max_rows=95)
            self._file_links(card, entry.get('file_refs', []), entry.get('attachments', []))
        else:
            self._render_activity(card, entry)

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
