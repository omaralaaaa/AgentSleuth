"""Application limits and Codex attachment markers."""

import re

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024  # Per attachment: 50 MiB
MAX_TOTAL_ATTACHMENT_BYTES = 250 * 1024 * 1024  # Per analysis: 250 MiB
DATA_URI = re.compile(r"^data:([^;,\s]+)?(?:;[^,\s]*)?;base64,(.*)$", re.I | re.S)
BASE64_FIELD_NAMES = {"image_url", "audio_url", "file_data", "b64_json", "base64", "base64_data"}
IMAGE_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "image/bmp": ".bmp"}
AUDIO_EXT = {"audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/ogg": ".ogg", "audio/flac": ".flac"}
SPECIAL_EXT = {"application/pdf": ".pdf", "text/plain": ".txt", "application/zip": ".zip"}
FILE_MARKER_RE = re.compile(r"</?(?:image|audio|file|attachment|document)\b[^>]*>", re.I)
FILE_PATH_RE = re.compile(r"\bpath\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)
FILE_NAME_RE = re.compile(r"\bname\s*=\s*(\[[^\]]*\]|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*'|[^\s>]+)", re.I)
