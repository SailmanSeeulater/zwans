"""Attachment names and content types."""

from __future__ import annotations

import mimetypes

from .errors import WikiError

_TYPES = {
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".pdf": "application/pdf",
    ".zip": "application/zip",
}


class BadAttachmentName(WikiError, ValueError):
    pass


def check_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise BadAttachmentName("an attachment needs a name")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise BadAttachmentName(f"{name!r} is not a file name")
    if name.startswith("."):
        raise BadAttachmentName("attachment names can't start with a dot")
    if len(name) > 100:
        raise BadAttachmentName("attachment names can be at most 100 characters")
    return name


def content_type(name: str) -> str:
    lowered = name.lower()
    for suffix, kind in _TYPES.items():
        if lowered.endswith(suffix):
            return kind
    guessed, _ = mimetypes.guess_type(name)
    return guessed or "application/octet-stream"


def is_image(kind: str) -> bool:
    return kind.startswith("image/")


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
