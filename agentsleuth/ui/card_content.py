"""Shared transcript card text and recorded fields for desktop frontends."""

import json
import ntpath
from pathlib import Path

from ..core.utils import safe_text
from .shell import shell_arguments


def card_heading(entry, agent_name):
    is_message = entry['kind'] == 'message'
    user = is_message and entry.get('role') == 'user'
    if entry.get('event_type') == 'assistant_error' and entry.get('agent') in ('opencode', 'claude'):
        label = 'AGENT ERROR'
    elif is_message:
        speaker = 'AGENT' if entry.get('agent') == 'claude' else agent_name.upper()
        label = 'USER' if user else speaker + (' · ' + entry['phase'] if entry.get('phase') else '')
    elif entry.get('agent') == 'claude' and 'execution' in entry:
        label = 'EXECUTION · ' + (entry['execution']['tool'] or 'TOOL')[:48].upper()
    else:
        activity_labels = {
            'CommandExecution': 'EXECUTION · COMMAND',
            'FileChange': 'EXECUTION · FILE CHANGE',
            'McpToolCall': 'EXECUTION · MCP TOOL',
            'DynamicToolCall': 'EXECUTION · DYNAMIC TOOL',
            'CollabAgentToolCall': 'EXECUTION · COLLAB AGENT',
            'ToolExecution': 'EXECUTION · TOOL',
            'reasoning': 'RECORDED REASONING',
            'file_attachment': 'FILE ATTACHMENT',
            'file_change': 'FILE CHANGE ARTIFACT',
            'scratch_file': 'SCRATCH FILE',
            'raw_part': 'PART EVIDENCE',
            'raw_message': 'MESSAGE EVIDENCE',
        }
        label = activity_labels.get(
            entry.get('activity_type'),
            'ACTIVITY · ' + entry.get('activity_type', 'UNKNOWN')
        )
    if 'timestamp_label' in entry:
        timestamp = entry['timestamp_label']
    else:
        recorded = entry.get('timestamp') or ''
        timestamp = recorded[:19].replace('T', ' ') + ' UTC' if recorded else ''
    meta = f'#{entry["ordinal"]}' + (f'  ·  {timestamp}' if timestamp else '')
    return label, meta


class CardContentMixin:
    def _populate_card(self, card, entry, bg):
        is_message = entry['kind'] == 'message'
        user = is_message and entry.get('role') == 'user'
        if entry.get('agent') == 'antigravity' and not user:
            self._field(card, 'Recorded step', entry.get('step_index'))
            if entry.get('truncated_fields'):
                self._field(card, 'Truncated in source', safe_text(entry['truncated_fields']))
        permission = entry.get('permission_mode', entry.get('permissions'))
        if user and entry.get('agent') != 'opencode' and permission is not None:
            self._card_permissions(card, permission)
        if is_message:
            self._body(card, entry.get('text', ''), bg)
            self._file_links(card, entry.get('file_refs', []), entry.get('attachments', []))
        elif 'execution' in entry:
            self._render_execution(card, entry)
        elif arguments := shell_arguments(entry):
            self._field(card, 'Tool', entry.get('tool_name'))
            self._field(card, 'Working directory', arguments.get('Cwd'))
            self._field(card, 'Shell command', arguments['command'], multiline=True,
                        command_styles=self._command_styles.pop(id(entry), None))
            other = {key: value for key, value in arguments.items()
                     if key not in ('command', 'CommandLine', 'Cwd')}
            self._field(card, 'Other input', other or None, multiline=True)
        elif entry.get('agent') == 'antigravity' and entry.get('part_type') == 'Tool request':
            self._field(card, 'Tool', entry.get('tool_name'))
            self._field(card, 'Input', entry.get('tool_arguments') or None, multiline=True)
        elif file := entry.get('scratch_file'):
            self._field(card, 'Bytes', file['size_bytes'])
            self._field(card, 'SHA-256', file.get('sha256'))
            self._field(card, 'Extraction error', file.get('error'))
            label = 'File preview (first 64 KiB)' if file.get('preview_truncated') else 'Recorded file content'
            self._field(card, label, file.get('preview'), multiline=True)
        elif entry.get('event_type') == 'file_attachment' and entry.get('attachments'):
            upload = entry['attachments'][0]
            self._field(card, 'MIME type', upload.get('mime'))
            self._field(card, 'Bytes', upload.get('size_bytes'))
            self._field(card, 'SHA-256', upload.get('sha256'))
            self._field(card, 'Extraction error', upload.get('error'))
        elif 'part_type' in entry:
            self._field(card, 'Part type', entry.get('part_type'))
            if 'text' in entry:
                self._body(card, entry['text'], bg)
            else:
                self._field(card, 'Recorded evidence', entry['evidence'], multiline=True, show_empty=True)
        else:
            self._render_activity_fields(card, entry)
        for file in entry.get('file_links', ()):
            self._filename_link(card, file['filename'], file['saved_path'], file['suffix'])

    def _render_execution(self, panel, entry):
        execution = entry['execution']
        self._field(panel, 'Tool', execution['tool'])
        if arguments := shell_arguments(entry):
            self._field(panel, 'Shell command', arguments['command'], multiline=True,
                        command_styles=self._command_styles.pop(id(entry), None))
            if entry.get('agent') == 'opencode':
                other = {key: value for key, value in arguments.items()
                         if key not in ('command', 'CommandLine', 'workdir', 'cwd', 'working_directory')}
                self._field(panel, 'Other input', other or None, multiline=True)
        else:
            self._field(panel, 'Input', execution['arguments'], multiline=True, show_empty=True)
        if execution['partial_input'] != execution['arguments']:
            self._field(panel, 'Recorded partial input', execution['partial_input'], multiline=True)
        self._field(panel, 'Recorded output', execution['output'], multiline=True, show_empty=True)
        self._field(panel, 'Recorded error', execution['error'], multiline=True, show_empty=True)
        status = execution['status']
        self._field(panel, 'Status', status if status is not None else 'Not recorded')
        if entry.get('agent') not in ('claude', 'opencode'):
            self._field(panel, 'Started', execution['start_label'])
            self._field(panel, 'Ended', execution['end_label'])
            self._field(panel, 'Metadata', execution['metadata'], multiline=True, show_empty=True)

    def _render_activity_fields(self, panel, activity):
        kind = activity['activity_type']
        hide_command_metadata = kind == 'CommandExecution' and activity.get('agent') == 'codex'
        if not hide_command_metadata:
            self._field(panel, 'Status', activity.get('status'))
        if kind == 'CommandExecution':
            if not hide_command_metadata:
                self._field(panel, 'Process ID', activity.get('pid'))
                self._field(panel, 'Working directory', activity.get('cwd'))
                self._field(panel, 'Exit code', activity.get('exit_code'))
            command = activity.get('command')
            self._field(panel, 'Shell command', command, multiline=True,
                        command_styles=self._command_styles.pop(id(activity), None))
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
        self._file_links(panel, [], activity.get('attachments', []))
