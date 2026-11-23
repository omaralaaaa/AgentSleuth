"""Antigravity summary index, generated transcripts and trajectory metadata."""

from .parser import load_threads, reconstruct_from_thread

name = 'Antigravity'
source_label = 'Evidence file'
source_hint = 'Select conversation_summaries.db, a transcript.jsonl, or a trajectory .db'
filetypes = [('Antigravity evidence', '*.db *.jsonl'), ('All files', '*.*')]
uses_output_directory = False
transcript_label = 'Antigravity evidence'
