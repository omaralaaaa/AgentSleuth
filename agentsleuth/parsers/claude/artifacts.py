"""Write bounded, non-overwriting copies of Claude evidence."""

import hashlib
import ntpath
import re
from pathlib import Path

from .paths import SESSION_ID


MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024


def filename(path):
    return ntpath.basename(path.rstrip('/\\')) or 'file'


class Artifacts:
    def __init__(self, output_root, evidence_root, session_id, project_paths):
        if not SESSION_ID.fullmatch(session_id):
            raise ValueError('Invalid Claude Code session identifier')
        self.root = output_root.expanduser().resolve()
        self.directory = self.root / 'Claude' / session_id
        self.evidence_root = evidence_root
        self.protected = [evidence_root]
        for value in set(project_paths):
            try:
                project = Path(value)
                if project.is_absolute():
                    self.protected.append(project.resolve())
            except (OSError, RuntimeError, ValueError):
                continue
        self.saved = {}
        self.total_bytes = 0

    def save(self, category, name, blob):
        if len(blob) > MAX_FILE_BYTES:
            raise ValueError('File exceeds the extraction size limit')
        digest = hashlib.sha256(blob).hexdigest()
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', name)[:100].strip(' .') or 'file'
        directory = self.directory / category
        target = directory / f'{digest[:24]}_{safe_name}'
        if directory.resolve() != directory or any(directory.is_relative_to(p) for p in self.protected):
            raise ValueError('Choose a results directory outside Claude evidence and recorded project directories')
        if target in self.saved:
            return self.saved[target]
        if self.total_bytes + len(blob) > MAX_TOTAL_BYTES:
            raise ValueError('Session exceeds the extraction size limit')
        directory.mkdir(parents=True, exist_ok=True)
        try:
            with target.open('xb') as stream:
                stream.write(blob)
        except FileExistsError:
            if (target.resolve() != target or not target.is_file()
                    or target.stat().st_size != len(blob) or target.read_bytes() != blob):
                raise ValueError('An existing results file has different evidence') from None
        result = {'saved_path': str(target), 'size_bytes': len(blob), 'sha256': digest}
        self.saved[target] = result
        self.total_bytes += len(blob)
        return result
