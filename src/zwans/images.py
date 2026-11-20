"""Images for the model: recognizing image files, and turning them into image blocks.

The API takes PNG, JPEG, GIF and WebP up to 5 MB once base64-encoded, and scales down
anything larger than about 1,568 pixels on its long side, so a big image costs about as much
as a medium one: roughly 1,600 tokens.
"""

import base64
import struct

from zwans.messages import ImageBlock, ImageSource

MAX_IMAGE_BYTES = 3_750_000  # 5 MB once base64-encoded, the API's limit


class ImageError(ValueError):
    pass


def media_type(data: bytes) -> str | None:
    """The image's type, from its first bytes rather than its name; None if it isn't one
    the API takes."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_block(data: bytes, name: str) -> ImageBlock:
    """An image block for `data`. Raises ImageError if it isn't an image the API takes, or
    is too big."""
    kind = media_type(data)
    if kind is None:
        raise ImageError(f"{name} isn't a PNG, JPEG, GIF or WebP image.")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(
            f"{name} is {len(data) / 1_000_000:.1f} MB; images can be at most "
            f"{MAX_IMAGE_BYTES / 1_000_000:.2f} MB. Make a smaller copy first."
        )
    encoded = base64.standard_b64encode(data).decode("ascii")
    return ImageBlock(source=ImageSource(media_type=kind, data=encoded))


def describe(data: bytes) -> str:
    """ "PNG image, 1200x800, 240 KB", or without the size when it can't be read quickly."""
    kind = (media_type(data) or "image/?").split("/")[1].upper()
    size = dimensions(data)
    shown = f", {size[0]}x{size[1]}" if size else ""
    return f"{kind} image{shown}, {max(len(data) // 1000, 1):,} KB"


def dimensions(data: bytes) -> tuple[int, int] | None:
    try:
        if data.startswith(b"\x89PNG"):
            width, height = struct.unpack(">II", data[16:24])
            return int(width), int(height)
        if data.startswith(b"GIF8"):
            width, height = struct.unpack("<HH", data[6:10])
            return int(width), int(height)
    except struct.error:
        return None
    return None
