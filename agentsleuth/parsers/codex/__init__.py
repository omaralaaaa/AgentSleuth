"""Codex evidence provider for SQLite thread indexes and JSONL rollouts."""

from .database import load_threads
from .reconstruction import reconstruct_from_thread

name = 'Codex'
source_label = 'State database'
source_hint = 'Select a Codex state_5.sqlite database'
filetypes = [('SQLite databases', '*.sqlite *.sqlite3 *.db'), ('All files', '*.*')]
