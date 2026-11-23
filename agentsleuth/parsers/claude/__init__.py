"""Claude Code evidence provider for history indexes and session JSONL transcripts."""

from .history import load_threads
from .parser import reconstruct_from_thread

name = 'Claude Code'
source_label = 'History index'
source_hint = 'Select a Claude Code history.jsonl file'
filetypes = [('Claude Code history', '*.jsonl'), ('All files', '*.*')]
transcript_label = 'Claude Code transcript'
sidebar_columns = (('cwd', 'Project', 140), ('updated_label', 'Last history (UTC)', 190),
                   ('created_label', 'First history (UTC)', 190), ('history_status', 'Transcript', 145))
