"""Write bounded, non-overwriting copies of Claude evidence."""

import base64
import ntpath
from pathlib import Path

from ...core.artifacts import ArtifactStore, MAX_FILE_BYTES
from ...core.export import ExportSession
from .paths import SESSION_ID



def filename(path):
    return ntpath.basename(path.rstrip('/\\')) or 'file'


def decode_base64(encoded):
    if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_FILE_BYTES + 2) // 3):
        raise ValueError('Missing or oversized Base64 content')
    blob = base64.b64decode(encoded, validate=True)
    if not blob or len(blob) > MAX_FILE_BYTES:
        raise ValueError('Empty or oversized Base64 content')
    return blob


class Artifacts(ArtifactStore):
    def __init__(self, output_root, evidence_root, session_id, project_paths, *, title=None):
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError('Invalid Claude Code session identifier')
        self.evidence_root = evidence_root
        protected = [evidence_root]
        for value in set(project_paths):
            try:
                project = Path(value)
                if project.is_absolute():
                    protected.append(project.resolve())
            except (OSError, RuntimeError, ValueError):
                continue
        super().__init__(ExportSession(output_root, 'Claude', session_id, title), protected)
