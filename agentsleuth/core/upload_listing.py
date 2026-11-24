"""Resolve exported files and group recorded uploads by user prompt."""

from pathlib import Path


def attachment_links(file_refs, attachments, output_directory):
    """Pair Codex filename markers with their extracted copies."""
    extracted = [item for item in attachments
                 if item.get('status') == 'extracted' and item.get('filename')]
    unused = dict(enumerate(extracted))
    for ref in file_refs:
        name = ref.get('filename')
        match = next((i for i, item in unused.items()
                      if name and item.get('original_filename') == name), None)
        if match is None:
            match = next((i for i, item in unused.items() if not item.get('original_filename')), None)
        item = unused.pop(match, {})
        yield dict(item, filename=name or item.get('filename') or 'Attachment',
                   saved_path=_attachment_path(item, output_directory))
    for item in unused.values():
        yield dict(item, filename=item.get('original_filename') or item['filename'],
                   saved_path=_attachment_path(item, output_directory))


def _attachment_path(item, directory):
    if path := item.get('saved_path'):
        return path
    if directory and item.get('filename'):
        return str(Path(directory) / 'attachments' / item['filename'])
    return None


def _existing_copy(directory, recorded_path):
    if not recorded_path:
        return None
    try:
        target = Path(recorded_path)
        if target.resolve() == target and target.is_relative_to(directory) and target.is_file():
            return target
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def export_folder(result):
    """Find a session folder that currently contains exported files."""
    if not (value := result.get('output_directory')):
        return None
    directory = Path(value)
    for name in ('attachments', 'recovered_files', 'scratch'):
        subfolder = directory / name
        try:
            if subfolder.resolve() == subfolder and any(
                    _existing_copy(directory, path) for path in subfolder.iterdir()):
                return directory
        except (OSError, RuntimeError, ValueError):
            continue
    return None


def prompt_uploads(result, directory):
    """Group direct message links and attachment-only OpenCode messages by prompt."""
    for turn_number, turn in enumerate(result['turns'], 1):
        groups = {}
        prompt_messages = {entry.get('message_id') for entry in turn['entries']
                           if entry.get('kind') == 'message' and entry.get('role') == 'user'}
        for entry in turn['entries']:
            if entry.get('role') != 'user':
                continue
            if entry.get('kind') == 'message':
                links = list(attachment_links(entry.get('file_refs', ()), entry.get('attachments', ()), directory))
                links.extend(entry.get('file_links') or ())
                key = ('prompt', entry['ordinal'])
            elif (entry.get('agent') == 'opencode' and entry.get('event_type') == 'file_attachment'
                  and entry.get('message_id') not in prompt_messages):
                links = entry.get('file_links') or ()
                key = ('attachment-only', entry.get('message_id') or entry['ordinal'])
            else:
                continue
            if not links:
                continue
            group = groups.setdefault(key, (entry['ordinal'], entry.get('text') or 'Attachment-only prompt', []))
            for link in links:
                target = _existing_copy(directory, link.get('saved_path'))
                status = ('Exported' if target else 'Copy missing' if link.get('saved_path') else
                          'Unavailable' if link.get('status') in ('error', 'skipped', 'unavailable') else
                          'Reference only')
                group[2].append((link.get('filename') or 'Attachment', target, status))
        for ordinal, text, files in groups.values():
            yield turn_number, ordinal, text, files
