"""OpenCode evidence provider for the shared conversation viewer."""

from .database import load_threads
from .parser import reconstruct_from_thread

name = 'OpenCode'
source_label = 'OpenCode database'
source_hint = 'Select an OpenCode opencode.db database'
filetypes = [('OpenCode database', '*.db *.sqlite *.sqlite3'), ('All files', '*.*')]
uses_output_directory = False
