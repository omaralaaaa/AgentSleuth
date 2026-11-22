"""Interpret stored filesystem paths across platforms."""

import ntpath
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse


def _path_from_stored(raw: str):
    value = raw.strip().strip('"')
    if value.startswith('file:'):
        parsed = urlparse(value)
        value = unquote(parsed.path)
        if re.match(r'^/[A-Za-z]:/', value):
            value = value[1:]
    if os.name == 'nt':
        value = value.replace('/', '\\')
    elif re.match(r'^[A-Za-z]:[\\/]', value):
        # When analysing a Windows disk mounted in Linux/WSL.
        drive, tail = ntpath.splitdrive(value)
        value = '/mnt/' + drive[0].lower() + '/' + tail.replace('\\', '/').lstrip('/')
    return Path(value)
