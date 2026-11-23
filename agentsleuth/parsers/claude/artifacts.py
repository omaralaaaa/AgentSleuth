"""Write bounded, non-overwriting copies of Claude evidence."""

import ntpath
from pathlib import Path

from ...core.artifacts import ArtifactStore, MAX_FILE_BYTES
from .paths import SESSION_ID



def filename(path):
    return ntpath.basename(path.rstrip('/\\')) or 'file'


class Artifacts(ArtifactStore):
    def __init__(self, output_root, evidence_root, session_id, project_paths):
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError('Invalid Claude Code session identifier')
        self.root = output_root.expanduser().resolve()
        self.evidence_root = evidence_root
        protected = [evidence_root]
        for value in set(project_paths):
            try:
                project = Path(value)
                if project.is_absolute():
                    protected.append(project.resolve())
            except (OSError, RuntimeError, ValueError):
                continue
        super().__init__(self.root / 'Claude' / session_id, protected)
