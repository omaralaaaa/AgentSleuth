"""Decode embedded attachments and normalize attachment references."""

import base64
import binascii
import hashlib
import mimetypes
import ntpath
import re

from .config import (
    MAX_ATTACHMENT_BYTES, MAX_TOTAL_ATTACHMENT_BYTES, DATA_URI,
    BASE64_FIELD_NAMES, IMAGE_EXT, AUDIO_EXT, SPECIAL_EXT,
    FILE_MARKER_RE, FILE_PATH_RE, FILE_NAME_RE,
)
from ...core.artifacts import write_session_artifact
from ...core.export import ExportSession
from ...core.utils import safe_text
from .metadata import get_turn


class AttachmentExtractor:
    """Only extracts explicit data URIs and known base64 attachment fields."""

    def __init__(self, destination):
        if isinstance(destination, ExportSession):
            self.destination, self.category = destination, 'attachments'
        else:
            self.destination, self.category = destination.parent, destination.name
        self.entries = []
        self.failures = []
        self.bytes_written = 0

    def _extension(self, mime):
        mime = mime.lower().split(";", 1)[0].strip()
        ext = IMAGE_EXT.get(mime) or AUDIO_EXT.get(mime) or SPECIAL_EXT.get(mime)
        if not ext:
            ext = mimetypes.guess_extension(mime) or ".bin"
        if not re.fullmatch(r"\.[a-zA-Z0-9]{1,8}", ext):
            ext = ".bin"
        return ext

    def _extract(self, encoded: str, mime: str, record: dict, field_path: str, original_filename=''):
        entry_id = len(self.entries) + len(self.failures) + 1
        marker = {"attachment_id": entry_id, "mime": mime, "source_field": field_path}
        if original_filename:
            marker["original_filename"] = original_filename
        # Prevent huge allocations; never dump the original base64 into results.
        encoded = re.sub(r"\s+", "", encoded)
        estimated = (len(encoded) * 3) // 4
        if estimated > MAX_ATTACHMENT_BYTES or self.bytes_written + estimated > MAX_TOTAL_ATTACHMENT_BYTES:
            error = "attachment size limit exceeded"
            self.failures.append({**marker, "error": error, "ordinal": record.get("ordinal")})
            return {"_embedded_attachment": {**marker, "status": "skipped", "reason": error}}
        try:
            # Supports usual Base64 and URL-safe Base64; pads unpadded data.
            payload = encoded.replace("-", "+").replace("_", "/")
            payload += "=" * (-len(payload) % 4)
            blob = base64.b64decode(payload, validate=True)
            if not blob:
                raise ValueError("empty decoded attachment")
            if len(blob) > MAX_ATTACHMENT_BYTES or self.bytes_written + len(blob) > MAX_TOTAL_ATTACHMENT_BYTES:
                raise ValueError("attachment size limit exceeded")
        except (ValueError, binascii.Error) as ex:
            error = str(ex)
            self.failures.append({**marker, "error": error, "ordinal": record.get("ordinal")})
            return {"_embedded_attachment": {**marker, "status": "error", "reason": error}}
        extension = ntpath.splitext(original_filename)[1]
        if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", extension):
            extension = self._extension(mime)
        filename = f"attachment_{entry_id:04d}{extension}"
        digest = hashlib.sha256(blob).hexdigest()
        file_path = write_session_artifact(
            self.destination, self.category, filename, blob,
            alternate_name=f"attachment_{entry_id:04d}_{digest[:10]}{extension}",
        )
        self.bytes_written += len(blob)
        result = {
            **marker,
            "status": "extracted",
            "filename": file_path.name,
            "saved_path": str(file_path),
            "size_bytes": len(blob),
            "sha256": digest,
            "ordinal": record.get("ordinal"),
            "turn_id": get_turn(record),
            "record_type": record.get("type"),
        }
        self.entries.append(result)
        return {"_embedded_attachment": result}

    def sanitize(self, obj, record, path="record", parent_type="", key="", original_filename='', mime_hint=''):
        if isinstance(obj, dict):
            current_type = str(obj.get("type") or parent_type)
            name = obj.get("filename")
            name = ntpath.basename(name) if isinstance(name, str) else ''
            mime = obj.get("mime_type") or obj.get("mime")
            mime = mime if isinstance(mime, str) else ''
            return {k: self.sanitize(v, record, f"{path}.{k}", current_type, k,
                                     name if k == "file_data" else '', mime if k == "file_data" else '')
                    for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.sanitize(v, record, f"{path}[{i}]", parent_type, key) for i, v in enumerate(obj)]
        if isinstance(obj, str):
            # A complete data:<MIME>;base64,... URI
            if obj.startswith("data:"):
                found = DATA_URI.match(obj)
                if found:
                    mime = found.group(1) or "application/octet-stream"
                    return self._extract(found.group(2), mime, record, path, original_filename)
            # A known *raw* base64 field, not arbitrary base64-looking text.
            is_audio_data = key == "data" and parent_type in {"input_audio", "audio"}
            if key == "file_data" or ((key in BASE64_FIELD_NAMES or is_audio_data) and len(obj) > 64):
                # Do not misinterpret HTTPS URLs as data.
                if obj.startswith(("http://", "https://", "file://")):
                    return obj
                if re.fullmatch(r"[A-Za-z0-9+/=_\-\s]+", obj):
                    mime = mime_hint or (
                        "audio/wav" if is_audio_data or key == "audio_url" else
                        "image/png" if key in ("image_url", "b64_json") else
                        "application/octet-stream"
                    )
                    return self._extract(obj, mime, record, path, original_filename)
        return obj

def extract_text_and_media(content):
    """Normalize the text and attachment refs in both rollout message formats."""
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return safe_text(content), []
    texts, attachments = [], []
    for part in content:
        if isinstance(part, str):
            texts.append(part)
            continue
        if not isinstance(part, dict):
            continue
        if isinstance(part.get("_embedded_attachment"), dict):
            attachments.append(part["_embedded_attachment"])
            continue
        for k in ("image_url", "audio_url", "file_data", "data"):
            if isinstance(part.get(k), dict) and isinstance(part[k].get("_embedded_attachment"), dict):
                attachments.append(part[k]["_embedded_attachment"])
        kind = part.get("type", "")
        text_value = part.get("text")
        if isinstance(text_value, str) and kind in {"input_text", "output_text", "text", "Text", "refusal"}:
            texts.append(text_value)
        elif kind in {"input_image", "input_audio", "image", "audio"}:
            if not attachments or attachments[-1].get("source_field") != kind:
                # The binary may have been a URL rather than embedded bytes.
                if not any(isinstance(part.get(k), dict) for k in ("image_url", "audio_url", "data")):
                    texts.append(f"[{kind}: external reference / no embedded bytes]")
    return "\n".join(t for t in texts if t).strip(), attachments

def extract_file_markers(text):
    """Remove Codex's visible attachment marker tags and retain path metadata.

    Example:
      <image name=[Image #1] path="D:\\evidence\\flag.png"></image>
    becomes a filename-only link target; the binary is never displayed or run.
    """
    refs = []

    def replace(match):
        tag = match.group(0)
        if tag.startswith("</"):
            return ""
        path_match = FILE_PATH_RE.search(tag)
        name_match = FILE_NAME_RE.search(tag)
        raw_path = ""
        if path_match:
            raw_path = next((v for v in path_match.groups() if v is not None), "").strip()
        raw_name = ""
        if name_match:
            raw_name = name_match.group(1).strip().strip('"\'')
            if raw_name.startswith("[") and raw_name.endswith("]"):
                raw_name = raw_name[1:-1].strip()
        filename = ntpath.basename(raw_path.replace("/", "\\")) if raw_path else ""
        filename = filename or raw_name or "Attachment"
        refs.append({
            "filename": filename,
            "path": raw_path,
            "tag": re.match(r"</?([a-z]+)", tag, re.I).group(1).lower(),
        })
        return ""

    cleaned = FILE_MARKER_RE.sub(replace, text or "")
    cleaned = re.sub(r"[ \t]*\n(?:[ \t]*\n){2,}", "\n\n", cleaned)
    return cleaned.strip(), refs

def all_embedded_refs(obj):
    found = []
    def visit(o):
        if isinstance(o, dict):
            att = o.get("_embedded_attachment")
            if isinstance(att, dict):
                found.append(att)
            else:
                for v in o.values():
                    visit(v)
        elif isinstance(o, list):
            for v in o:
                visit(v)
    visit(obj)
    return found
