"""The ImageDiff tool: what changed between two images, such as screenshots before and after
a CSS change.

Looking at two screenshots side by side, a model misses a button that moved four pixels or
a margin that grew, and claims a change it can't see. This compares them pixel by pixel and
says how much changed and where: the share of pixels that changed, the changed areas as
rectangles, and one picture of the after image dimmed, with the changed areas in full color,
outlined and tinted red, so the model looks at what changed instead of hunting for it.

PNG is decoded here, in Python, with no imaging library; JPEG, WebP and the PNGs this can't
decode are converted to PNG with ffmpeg when it's installed. The comparison works on whole
rows as big integers rather than pixel by pixel, so a pair of 1280x800 screenshots takes
well under a second.
"""

import secrets
import shutil
import struct
import zlib
from dataclasses import dataclass
from itertools import accumulate
from operator import itemgetter
from typing import Any

from pydantic import BaseModel, Field

from zwans.images import MAX_IMAGE_BYTES, image_block, media_type
from zwans.tools.base import ToolContext, ToolError, ToolOutput

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # PNG color type -> samples per pixel
MAX_PIXELS = 25_000_000  # in one image: a full-page screenshot 1280 wide is about 20 million
CELL = 16  # pixels on the side of the squares changes are grouped in
MAX_REGIONS = 10
MAX_WIDTH = 1280  # of the picture returned
FFMPEG_TIMEOUT = 60
LOW7 = 0x7F
BYTE = (255).__and__


class PngError(ValueError):
    """The data isn't a PNG this module can decode."""


class UnsupportedPng(PngError):
    """A valid PNG in a form this module doesn't decode (interlaced, or not 8 bits)."""


@dataclass(frozen=True)
class Bitmap:
    width: int
    height: int
    rgba: bytes  # 4 bytes a pixel, rows from the top


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    width: int
    height: int
    changed: int  # pixels changed inside it


class ImageDiffInput(BaseModel):
    before: str = Field(description="The first image, relative to the workspace root.")
    path: str = Field(description="The second image, the one after the change.")
    threshold: int = Field(
        default=24,
        ge=0,
        le=254,
        description="How much a color channel (0-255) must differ for a pixel to count as "
        "changed. The default ignores anti-aliasing and compression noise; 0 counts any "
        "difference.",
    )


class ImageDiffTool:
    name = "ImageDiff"
    description = (
        "Compare two images, such as screenshots before and after a change, and see what "
        "changed: the share of pixels that differ, the changed areas as x,y,w,h rectangles, "
        "and a picture of the after image dimmed with the changed areas outlined in red. Use "
        "it to check that a change did what you meant and nothing else, instead of looking at "
        "two screenshots side by side. PNG works anywhere; JPEG and WebP need ffmpeg."
    )
    input_model = ImageDiffInput
    read_only = True

    def read_paths(self, args: dict[str, Any]) -> list[str]:
        """Both images, for the policy: a Read rule refusing either refuses the call."""
        return [p for p in (args.get("before"), args.get("path")) if isinstance(p, str)]

    async def run(self, args: ImageDiffInput, ctx: ToolContext) -> ToolOutput:
        before = await _load(args.before, ctx)
        after = await _load(args.path, ctx)
        width, height = min(before.width, after.width), min(before.height, after.height)
        lines = [
            f"{args.before}: {before.width}x{before.height}. "
            f"{args.path}: {after.width}x{after.height}."
        ]
        if (before.width, before.height) != (after.width, after.height):
            lines.append(
                f"The images differ in size, so only the overlapping {width}x{height} from "
                "the top left is compared."
            )
        old, new = crop(before, width, height), crop(after, width, height)
        total = width * height
        if old == new:
            lines.append("The compared pixels are identical.")
            return ToolOutput(content="\n".join(lines))
        mask = changed_pixels(old, new, args.threshold)
        count = mask.count(b"\x80")
        if not count:
            slight = changed_pixels(old, new, 0).count(b"\x80")
            lines.append(
                f"No pixel differs by more than {args.threshold} in any channel; {slight:,} "
                f"differ by less ({_share(slight, total)}). Use a lower threshold to see them."
            )
            return ToolOutput(content="\n".join(lines))
        regions = find_regions(mask, width, height)
        lines.append(
            f"{_share(count, total)} of the pixels changed ({count:,} of {total:,}, by more than "
            f"{args.threshold} in some channel), in {len(regions)} "
            f"region{'s' if len(regions) != 1 else ''}"
            + (f"; the {MAX_REGIONS} largest:" if len(regions) > MAX_REGIONS else ":")
        )
        for region in regions[:MAX_REGIONS]:
            lines.append(
                f"  x={region.x} y={region.y} w={region.width} h={region.height}"
                f"  ({region.changed:,} pixel{'s' if region.changed != 1 else ''} changed, "
                f"{_share(region.changed, region.width * region.height)} of the box)"
            )
        picture, shown = overlay(after, mask, width, height, regions)
        resized = shown != (after.width, after.height)
        scaled = f", scaled to {shown[0]}x{shown[1]}" if resized else ""
        lines.append(
            f"The picture is {args.path} dimmed, with the changed regions in full color, "
            f"outlined in red and their changed pixels tinted red{scaled}."
        )
        return ToolOutput(content="\n".join(lines), images=(image_block(picture, "the diff"),))


def _share(part: int, whole: int) -> str:
    if not whole:
        return "0%"
    share = 100 * part / whole
    return f"{share:.2f}%" if share < 1 else f"{share:.1f}%"


async def _load(path: str, ctx: ToolContext) -> Bitmap:
    try:
        data = await ctx.executor.read_bytes(path)
    except IsADirectoryError:
        raise ToolError(f"{path} is a folder, not an image.") from None
    problem = ""
    if data.startswith(PNG_SIGNATURE):
        try:
            return decode_png(data)
        except UnsupportedPng as exc:
            problem = str(exc)
        except PngError as exc:
            raise ToolError(f"{path} isn't a valid PNG: {exc}") from exc
    elif media_type(data) is None:
        raise ToolError(f"{path} isn't a PNG, JPEG, GIF or WebP image.")
    if shutil.which("ffmpeg") is None:
        kind = problem or f"it's a {(media_type(data) or '?').split('/')[1].upper()}"
        raise ToolError(
            f"{path} can't be decoded here ({kind}). Install ffmpeg to compare it, or save it "
            "as an 8-bit, non-interlaced PNG."
        )
    return decode_png(await _convert(path, ctx))


async def _convert(path: str, ctx: ToolContext) -> bytes:
    """The image as a PNG this module decodes, made by ffmpeg in a hidden file in the
    workspace, which is removed afterwards."""
    source = ctx.executor.relative(path)
    if source.startswith("-"):
        source = "./" + source
    temp = f".zwans-imagediff-{secrets.token_hex(4)}.png"
    argv = ["ffmpeg", "-v", "error", "-y", "-i", source, "-frames:v", "1", "-update", "1"]
    argv += ["-pix_fmt", "rgba", "-pred", "none", temp]
    try:
        result = await ctx.executor.run(argv, timeout=FFMPEG_TIMEOUT)
        if result.exit_code != 0:
            detail = result.output.strip()[-500:] or f"exit code {result.exit_code}"
            raise ToolError(f"ffmpeg couldn't convert {path}: {detail}")
        try:
            converted = await ctx.executor.read_bytes(temp)
        except FileNotFoundError:
            raise ToolError(f"ffmpeg wrote nothing for {path}.") from None
    finally:
        await ctx.executor.run(["rm", "-f", temp], timeout=30)
    return converted


# -- PNG


def decode_png(data: bytes) -> Bitmap:
    """Decode an 8-bit, non-interlaced PNG of any color type to RGBA."""
    if not data.startswith(PNG_SIGNATURE):
        raise PngError("it doesn't start with the PNG signature")
    pos = len(PNG_SIGNATURE)
    header: tuple[int, ...] | None = None
    palette = b""
    transparency = b""
    idat: list[bytes] = []
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body[:13])
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None or not idat:
        raise PngError("it has no image header or no image data")
    width, height, depth, color, _, _, interlace = header
    if color not in CHANNELS:
        raise PngError(f"unknown color type {color}")
    if depth != 8:
        raise UnsupportedPng(f"it has {depth}-bit samples; only 8-bit PNGs are decoded here")
    if interlace:
        raise UnsupportedPng("it's an interlaced PNG, which isn't decoded here")
    if not width or not height:
        raise PngError("it has no pixels")
    if width * height > MAX_PIXELS:
        raise PngError(f"it's {width}x{height}, more than {MAX_PIXELS:,} pixels")
    bpp = CHANNELS[color]
    stride = width * bpp
    expected = (stride + 1) * height
    try:
        inflater = zlib.decompressobj()
        raw = inflater.decompress(b"".join(idat), expected)
    except zlib.error as exc:
        raise PngError(f"its image data is corrupt ({exc})") from exc
    if len(raw) < expected:
        raise PngError("its image data is cut short")
    samples = _unfilter(raw, height, stride, bpp)
    return Bitmap(width, height, _to_rgba(samples, width * height, color, palette, transparency))


def _unfilter(raw: bytes, height: int, stride: int, bpp: int) -> bytes:
    rows: list[bytes] = []
    previous = bytes(stride)
    pos = 0
    for _ in range(height):
        kind = raw[pos]
        line = raw[pos + 1 : pos + 1 + stride]
        pos += 1 + stride
        if kind == 0:
            current = line
        elif kind == 1:
            current = _sub(line, bpp)
        elif kind == 2:
            current = _add(line, previous)
        elif kind == 3:
            current = _average(line, previous, bpp)
        elif kind == 4:
            current = _paeth(line, previous, bpp)
        else:
            raise PngError(f"a row has the unknown filter {kind}")
        rows.append(current)
        previous = current
    return b"".join(rows)


def _lanes(byte: int, count: int) -> int:
    return int.from_bytes(bytes([byte]) * count, "little")


def _add(a: bytes, b: bytes) -> bytes:
    """a + b, byte by byte, modulo 256, on the rows as two big integers: the low seven bits
    of each byte are added without carrying into the next byte, and the top bit is xor'd."""
    n = len(a)
    x, y = int.from_bytes(a, "little"), int.from_bytes(b, "little")
    low, high = _lanes(LOW7, n), _lanes(0x80, n)
    return (((x & low) + (y & low)) ^ ((x ^ y) & high)).to_bytes(n, "little")


def _sub(line: bytes, bpp: int) -> bytes:
    out = bytearray(len(line))
    for channel in range(bpp):
        out[channel::bpp] = bytes(map(BYTE, accumulate(line[channel::bpp])))
    return bytes(out)


def _average(line: bytes, previous: bytes, bpp: int) -> bytes:
    out = bytearray(line)
    for i in range(min(bpp, len(out))):
        out[i] = (out[i] + (previous[i] >> 1)) & 255
    for i in range(bpp, len(out)):
        out[i] = (out[i] + ((out[i - bpp] + previous[i]) >> 1)) & 255
    return bytes(out)


def _paeth(line: bytes, previous: bytes, bpp: int) -> bytes:
    out = bytearray(line)
    for i in range(min(bpp, len(out))):
        out[i] = (out[i] + previous[i]) & 255
    for i in range(bpp, len(out)):
        a = out[i - bpp]
        b = previous[i]
        c = previous[i - bpp]
        pa = b - c if b > c else c - b
        pb = a - c if a > c else c - a
        pc = a + b - c - c
        if pc < 0:
            pc = -pc
        if pa <= pb and pa <= pc:
            out[i] = (out[i] + a) & 255
        elif pb <= pc:
            out[i] = (out[i] + b) & 255
        else:
            out[i] = (out[i] + c) & 255
    return bytes(out)


def _to_rgba(samples: bytes, pixels: int, color: int, palette: bytes, alpha: bytes) -> bytes:
    if color == 6:
        return samples
    out = bytearray(pixels * 4)
    if color == 2:
        for channel in range(3):
            out[channel::4] = samples[channel::3]
        out[3::4] = b"\xff" * pixels
    elif color == 0:
        for channel in range(3):
            out[channel::4] = samples
        out[3::4] = b"\xff" * pixels
    elif color == 4:
        for channel in range(3):
            out[channel::4] = samples[0::2]
        out[3::4] = samples[1::2]
    else:  # a palette
        if not palette:
            raise PngError("it uses a palette but has none")
        entries = palette[: len(palette) // 3 * 3].ljust(768, b"\x00")
        opacity = alpha[:256].ljust(256, b"\xff")
        for channel in range(3):
            out[channel::4] = samples.translate(entries[channel::3])
        out[3::4] = samples.translate(opacity)
    return bytes(out)


def encode_png(width: int, height: int, pixels: bytes, channels: int = 3) -> bytes:
    """A PNG of 8-bit gray (1), gray and alpha (2), RGB (3) or RGBA (4) pixels, every row
    unfiltered."""
    color = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    stride = width * channels
    raw = b"".join(b"\x00" + pixels[y * stride : (y + 1) * stride] for y in range(height))

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


# -- Comparing


def crop(image: Bitmap, width: int, height: int) -> bytes:
    """The image's top-left width x height pixels, as RGBA."""
    if (image.width, image.height) == (width, height):
        return image.rgba
    stride, keep = image.width * 4, width * 4
    return b"".join(image.rgba[y * stride : y * stride + keep] for y in range(height))


def changed_pixels(old: bytes, new: bytes, threshold: int) -> bytes:
    """One byte a pixel, 0x80 where some channel differs by more than `threshold`, else 0.

    Each channel byte is widened to a 16-bit lane of one big integer, so a whole image is
    compared with a few integer operations: lane = 256 + old - new lies in 1..511, and adding
    or subtracting a constant sets a lane's top bit exactly when it's out of range."""
    n = len(old)
    ones = _lanes16(n)
    a, b = _widen(old), _widen(new)
    difference = a + (ones << 8) - b
    above = difference + ones * (0x8000 - 257 - threshold)  # old - new > threshold
    below = ones * (0x8000 + 255 - threshold) - difference  # new - old > threshold
    flags = ((above | below) & (ones << 15)).to_bytes(2 * n, "little")[1::2]
    pixels = int.from_bytes(flags[0::4], "little")
    for channel in range(1, 4):
        pixels |= int.from_bytes(flags[channel::4], "little")
    return pixels.to_bytes(n // 4, "little")


def _lanes16(count: int) -> int:
    return int.from_bytes(b"\x01\x00" * count, "little")


def _widen(data: bytes) -> int:
    wide = bytearray(2 * len(data))
    wide[0::2] = data
    return int.from_bytes(wide, "little")


def find_regions(mask: bytes, width: int, height: int) -> list[Region]:
    """The changed areas, largest first: CELL-sized squares with a change in them, joined
    where they touch (corners too), each shrunk to the changed pixels' bounds."""
    columns = (width + CELL - 1) // CELL
    cells: set[tuple[int, int]] = set()
    for cy in range(0, (height + CELL - 1) // CELL):
        band = 0
        for y in range(cy * CELL, min((cy + 1) * CELL, height)):
            band |= int.from_bytes(mask[y * width : (y + 1) * width], "big")
        if not band:
            continue
        merged = band.to_bytes(width, "big")
        cells.update(
            (cx, cy) for cx in range(columns) if 0x80 in merged[cx * CELL : (cx + 1) * CELL]
        )
    regions: list[Region] = []
    while cells:
        start = cells.pop()
        group = [start]
        stack = [start]
        while stack:
            cx, cy = stack.pop()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    near = (cx + dx, cy + dy)
                    if near in cells:
                        cells.remove(near)
                        group.append(near)
                        stack.append(near)
        x0 = min(c[0] for c in group) * CELL
        x1 = min((max(c[0] for c in group) + 1) * CELL, width)
        y0 = min(c[1] for c in group) * CELL
        y1 = min((max(c[1] for c in group) + 1) * CELL, height)
        regions.append(_tighten(mask, width, x0, y0, x1, y1))
    regions = _merge(regions)
    regions.sort(key=lambda r: (-r.changed, r.y, r.x))
    return regions


def _merge(regions: list[Region]) -> list[Region]:
    """Regions whose boxes overlap, joined into one, until none overlap."""
    merged = True
    while merged:
        merged = False
        for i, a in enumerate(regions):
            for j in range(i + 1, len(regions)):
                b = regions[j]
                if (
                    a.x < b.x + b.width
                    and b.x < a.x + a.width
                    and a.y < b.y + b.height
                    and b.y < a.y + a.height
                ):
                    x0, y0 = min(a.x, b.x), min(a.y, b.y)
                    x1 = max(a.x + a.width, b.x + b.width)
                    y1 = max(a.y + a.height, b.y + b.height)
                    joined = Region(x0, y0, x1 - x0, y1 - y0, a.changed + b.changed)
                    regions = [r for k, r in enumerate(regions) if k not in (i, j)] + [joined]
                    merged = True
                    break
            if merged:
                break
    return regions


def _tighten(mask: bytes, width: int, x0: int, y0: int, x1: int, y1: int) -> Region:
    left, right, top, bottom, changed = x1, x0, y1, y0, 0
    for y in range(y0, y1):
        row = mask[y * width + x0 : y * width + x1]
        first = row.find(0x80)
        if first < 0:
            continue
        changed += row.count(0x80)
        left = min(left, x0 + first)
        right = max(right, x0 + row.rfind(0x80) + 1)
        top = min(top, y)
        bottom = y + 1
    return Region(left, top, right - left, bottom - top, changed)


# -- The picture


def overlay(
    after: Bitmap, mask: bytes, width: int, height: int, regions: list[Region]
) -> tuple[bytes, tuple[int, int]]:
    """A PNG of the after image dimmed, the regions in full color with their changed pixels
    tinted red and a red outline, at most MAX_WIDTH wide; and its size."""
    full_w, full_h = after.width, after.height
    pixels = full_w * full_h
    if (width, height) != (full_w, full_h):  # the mask covers the overlap only
        wide = bytearray(pixels)
        for y in range(height):
            wide[y * full_w : y * full_w + width] = mask[y * width : (y + 1) * width]
        mask = bytes(wide)
    on = int.from_bytes(mask.translate(bytes([0] * 128 + [255] * 128)), "little")
    off = int.from_bytes(mask.translate(bytes([255] * 128 + [0] * 128)), "little")
    half = bytes(v // 2 for v in range(256))
    tints = (bytes(v // 2 + 128 for v in range(256)), half, half)
    dim = bytes(int(v * 0.4 + 40) for v in range(256))
    channels: list[bytearray] = []
    for channel, tint in zip(range(3), tints, strict=True):
        plain = after.rgba[channel::4]
        tinted = (int.from_bytes(plain.translate(tint), "little") & on) | (
            int.from_bytes(plain, "little") & off
        )
        bright = tinted.to_bytes(pixels, "little")
        dimmed = bytearray(plain.translate(dim))
        for r in regions:
            for y in range(r.y, r.y + r.height):
                start = y * full_w + r.x
                dimmed[start : start + r.width] = bright[start : start + r.width]
        channels.append(dimmed)
    thickness = max(2, -(-2 * full_w // MAX_WIDTH))
    for r in regions:
        _outline(channels, full_w, full_h, r, thickness)
    rgb = bytearray(pixels * 3)
    for channel in range(3):
        rgb[channel::3] = channels[channel]
    out_w = min(full_w, MAX_WIDTH)
    while True:
        out_h = max(1, round(full_h * out_w / full_w))
        scaled = _scale(bytes(rgb), full_w, full_h, out_w, out_h)
        png = encode_png(out_w, out_h, scaled, 3)
        if len(png) <= MAX_IMAGE_BYTES or out_w <= 200:
            return png, (out_w, out_h)
        out_w //= 2


def _outline(channels: list[bytearray], width: int, height: int, r: Region, thickness: int) -> None:
    x0, y0 = max(r.x - thickness, 0), max(r.y - thickness, 0)
    x1, y1 = min(r.x + r.width + thickness, width), min(r.y + r.height + thickness, height)
    color = (255, 0, 0)
    for channel, value in zip(channels, color, strict=True):
        span = bytes([value]) * (x1 - x0)
        edge = bytes([value]) * thickness
        for y in range(y0, y1):
            row = y * width
            if y < r.y or y >= r.y + r.height:
                channel[row + x0 : row + x1] = span
            else:
                left = min(thickness, r.x - x0)
                channel[row + x0 : row + x0 + left] = edge[:left]
                right = min(thickness, x1 - (r.x + r.width))
                channel[row + x1 - right : row + x1] = edge[:right]


def _scale(rgb: bytes, width: int, height: int, out_w: int, out_h: int) -> bytes:
    """Nearest-neighbour scaling of RGB pixels."""
    if (out_w, out_h) == (width, height):
        return rgb
    picks = [3 * (x * width // out_w) + c for x in range(out_w) for c in range(3)]
    take = itemgetter(*picks)
    stride = width * 3
    rows = []
    for y in range(out_h):
        source = (y * height // out_h) * stride
        rows.append(bytes(take(rgb[source : source + stride])))
    return b"".join(rows)
