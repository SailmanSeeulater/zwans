"""The Video tool: a video file as a model can take it in, a few frames and what's said.

Models read text and images, not video, and a frame a second of a ten-minute video would
cost about a million tokens. Video sends a contact sheet instead: frames spread evenly over
the video, or the part of it asked for, tiled into one image of about 1,600 tokens, with
each one's time. With it comes the transcript: from subtitles beside the file or inside it,
or from Whisper when it's installed. A closer look is another call with a narrower range.

ffmpeg does the work, run where commands run (in the sandbox, if there is one), so the
pictures it makes go to a scratch folder in the workspace, which goes when the call ends.
"""

import json
import math
import re
import secrets
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field

from zwans.executor.base import CommandResult
from zwans.images import ImageError, image_block
from zwans.messages import ImageBlock
from zwans.tools.base import ToolContext, ToolError, ToolOutput

DEFAULT_FRAMES = 9
MAX_FRAMES = 16
SHEET_WIDTH = 1500  # pixels across the contact sheet; the API scales anything wider down
SINGLE_WIDTH = 1280  # one frame on its own
MAX_TRANSCRIPT_CHARS = 30_000  # about 7,500 tokens
PROBE_TIMEOUT = 30.0
FRAME_TIMEOUT = 60.0
WHISPER_TIMEOUT = 900.0
WHISPER_MODEL = "base"  # quick and small; good enough for speech that's clear
SIDECARS = (".srt", ".vtt", ".en.srt", ".en.vtt")
INSTALL = "ffmpeg isn't installed where commands run (on a Mac: brew install ffmpeg)."


class VideoInput(BaseModel):
    path: str = Field(description="Path to the video file, relative to the workspace root.")
    start: str | None = Field(
        default=None,
        description='Where to start, as "1:30", "90" or "1:02:03". Leave it out for the start.',
    )
    end: str | None = Field(
        default=None, description="Where to stop, written the same way. Leave it out for the end."
    )
    frames: int = Field(
        default=DEFAULT_FRAMES,
        ge=0,
        le=MAX_FRAMES,
        description="How many frames to show, spread evenly over the range and tiled into "
        "one image. 0 for none, only the transcript.",
    )
    transcript: bool = Field(default=True, description="Include what's said, with its times.")


@dataclass
class Info:
    """What ffprobe says about a video."""

    duration: float
    width: int = 0
    height: int = 0
    fps: float = 0.0
    codec: str = ""
    sound: bool = False
    subtitles: list[tuple[int, str]] = field(default_factory=list)  # (stream, language)

    def describe(self) -> str:
        parts = [clock(self.duration)]
        if self.width and self.height:
            parts.append(f"{self.width}x{self.height}")
        if self.fps:
            parts.append(f"{self.fps:.3g} fps")
        if self.codec:
            parts.append(self.codec)
        parts.append("with sound" if self.sound else "no sound")
        if self.subtitles:
            count = len(self.subtitles)
            parts.append(f"{count} subtitle track{'s' if count > 1 else ''}")
        return ", ".join(parts)


class VideoTool:
    name = "Video"
    description = (
        "Watch a video file in the workspace: get frames spread evenly over it, tiled into "
        "one image with each frame's time, and the transcript of what's said, with times. "
        "For a closer look at a moment, call it again with start and end around it. "
        "The transcript comes from subtitles beside the file or in it, or from Whisper "
        "when it's installed, which takes a while for a long video, so give a range."
    )
    input_model = VideoInput
    read_only = True  # its scratch folder goes when the call ends

    async def run(self, args: VideoInput, ctx: ToolContext) -> ToolOutput:
        path = ctx.executor.relative(args.path)
        info = await _probe(ctx, path)
        start = parse_time(args.start, "start") if args.start else 0.0
        end = parse_time(args.end, "end") if args.end else info.duration
        end = min(end, info.duration) if info.duration else end
        if start >= end:
            length = clock(info.duration)
            raise ToolError(
                f"Nothing to show between {clock(start)} and {clock(end)}: {path} is {length} long."
            )
        lines = [f"{path}: {info.describe()}"]
        images: tuple[ImageBlock, ...] = ()
        scratch = f".zwans-video-{secrets.token_hex(4)}"
        await ctx.executor.run(["mkdir", "-p", scratch], timeout=PROBE_TIMEOUT)
        try:
            if args.frames:
                sheet, times = await _sheet(ctx, path, scratch, start, end, args.frames)
                if sheet is not None:
                    images = (sheet,)
                    lines.append(_caption(times, start, end))
                else:
                    lines.append("(No frames could be taken from that range.)")
            if args.transcript:
                lines.append("")
                lines.append(await _transcript(ctx, path, scratch, info, start, end))
        finally:
            await ctx.executor.run(["rm", "-rf", scratch], timeout=PROBE_TIMEOUT)
        return ToolOutput(content="\n".join(lines), images=images)


# -- times


def parse_time(text: str, what: str) -> float:
    """Seconds from "90", "1:30", "1:02:03" or "1:30.5"."""
    pieces = text.strip().split(":")
    try:
        if not 1 <= len(pieces) <= 3:
            raise ValueError
        seconds = 0.0
        for piece in pieces:
            value = float(piece)
            if value < 0:
                raise ValueError
            seconds = seconds * 60 + value
    except ValueError:
        raise ToolError(f'{what} should be a time such as "1:30" or "90", not {text!r}.') from None
    return seconds


def clock(seconds: float) -> str:
    """1:05, or 1:02:03 past an hour."""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


# -- ffmpeg


async def _run(ctx: ToolContext, argv: list[str], timeout: float) -> CommandResult:
    try:
        result = await ctx.executor.run(argv, timeout=timeout)
    except FileNotFoundError:
        missing = INSTALL if argv[0].startswith("ff") else f"{argv[0]} isn't installed."
        raise ToolError(missing) from None
    if result.exit_code == 127 and argv[0].startswith("ff"):
        raise ToolError(INSTALL)
    return result


async def _probe(ctx: ToolContext, path: str) -> Info:
    argv = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams"]
    result = await _run(ctx, [*argv, path], PROBE_TIMEOUT)
    # Its messages and its JSON come out together: the JSON is from the first { to the last }.
    output = result.output
    opening, closing = output.find("{"), output.rfind("}")
    said = (output[:opening] if opening >= 0 else output).strip()
    if result.exit_code != 0:
        if "No such file" in said:
            raise ToolError(f"There is no {path}.")
        problem = said.splitlines()[-1] if said else "ffprobe failed"
        raise ToolError(f"{path} couldn't be read as a video: {problem}")
    try:
        data = json.loads(output[opening : closing + 1])
    except ValueError:
        raise ToolError(f"{path} couldn't be read as a video.") from None
    streams: list[dict[str, Any]] = data.get("streams") or []
    video = next(
        (
            s
            for s in streams
            if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    if video is None:
        raise ToolError(f"{path} has no video in it.")
    duration = _number(data.get("format", {}).get("duration")) or _number(video.get("duration"))
    return Info(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        codec=str(video.get("codec_name") or ""),
        sound=any(s.get("codec_type") == "audio" for s in streams),
        subtitles=[
            (int(s["index"]), str(s.get("tags", {}).get("language") or ""))
            for s in streams
            if s.get("codec_type") == "subtitle" and "index" in s
        ],
    )


def _number(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _rate(value: object) -> float:
    if not isinstance(value, str) or "/" not in value:
        return _number(value)
    top, _, bottom = value.partition("/")
    return _number(top) / _number(bottom) if _number(bottom) else 0.0


async def _sheet(
    ctx: ToolContext, path: str, scratch: str, start: float, end: float, count: int
) -> tuple[ImageBlock | None, list[float]]:
    """The frames tiled into one image, and the time of each one that could be taken."""
    span = end - start
    columns = math.ceil(math.sqrt(count))
    width = SINGLE_WIDTH if count == 1 else SHEET_WIDTH // columns
    times: list[float] = []
    for n in range(count):
        at = start + (n + 0.5) * span / count
        target = f"{scratch}/f{len(times):02d}.png"
        argv = ["ffmpeg", "-v", "error", "-ss", f"{at:.3f}", "-i", path, "-frames:v", "1"]
        result = await _run(ctx, [*argv, "-vf", f"scale={width}:-2", "-y", target], FRAME_TIMEOUT)
        if result.exit_code == 0 and await _exists(ctx, target):
            times.append(at)
    if not times:
        return None, []
    if len(times) == 1:
        data = await ctx.executor.read_bytes(f"{scratch}/f00.png")
    else:
        rows = math.ceil(len(times) / columns)
        tile = f"tile={columns}x{rows}:padding=6:color=white"
        argv = ["ffmpeg", "-v", "error", "-framerate", "1", "-i", f"{scratch}/f%02d.png"]
        sheet = f"{scratch}/sheet.jpg"
        argv += ["-vf", tile, "-frames:v", "1", "-q:v", "3", "-y", sheet]
        result = await _run(ctx, argv, FRAME_TIMEOUT)
        if result.exit_code != 0:
            raise ToolError(f"The frames couldn't be put together: {result.output.strip()}")
        data = await ctx.executor.read_bytes(sheet)
    try:
        return image_block(data, path), times
    except ImageError as exc:
        raise ToolError(str(exc)) from exc


async def _exists(ctx: ToolContext, path: str) -> bool:
    try:
        await ctx.executor.read_bytes(path)
    except OSError:
        return False
    return True


def _caption(times: list[float], start: float, end: float) -> str:
    if len(times) == 1:
        return f"The frame at {clock(times[0])}."
    each = ", ".join(f"{n} at {clock(at)}" for n, at in enumerate(times, 1))
    return (
        f"{len(times)} frames from {clock(start)} to {clock(end)}, left to right and top to "
        f"bottom: {each}."
    )


# -- the transcript


async def _transcript(
    ctx: ToolContext, path: str, scratch: str, info: Info, start: float, end: float
) -> str:
    found = await _subtitles(ctx, path, scratch, info)
    offset = 0.0
    if found is None and info.sound and await _has_whisper(ctx):
        found = await _whisper(ctx, path, scratch, start, end)
        offset = start  # Whisper heard only the range, so its times start there
    if found is None:
        if not info.sound:
            return "No transcript: the video has no sound and no subtitles."
        return (
            "No transcript: there are no subtitles beside the file or in it, and Whisper "
            "isn't installed where commands run (pip install openai-whisper)."
        )
    source, text = found
    cues = [(at + offset, words) for at, words in parse_cues(text)]
    shown = [f"[{clock(at)}] {words}" for at, words in cues if start - 1 <= at <= end]
    if not shown:
        return f"Transcript ({source}): nothing is said between {clock(start)} and {clock(end)}."
    body = "\n".join(shown)
    note = ""
    if len(body) > MAX_TRANSCRIPT_CHARS:
        body = body[:MAX_TRANSCRIPT_CHARS].rsplit("\n", 1)[0]
        note = "\n[The transcript goes on: give a later start to read more.]"
    return f"Transcript ({source}):\n{body}{note}"


async def _subtitles(
    ctx: ToolContext, path: str, scratch: str, info: Info
) -> tuple[str, str] | None:
    """(where they came from, their text): a file beside the video, or a track in it."""
    stem = str(PurePosixPath(path).with_suffix(""))
    for suffix in SIDECARS:
        try:
            data = await ctx.executor.read_bytes(stem + suffix)
        except OSError:
            continue
        return f"from {PurePosixPath(stem + suffix).name}", data.decode("utf-8", "replace")
    tracks = sorted(info.subtitles, key=lambda track: track[1] not in ("eng", "en"))
    for index, language in tracks:
        target = f"{scratch}/track{index}.srt"
        argv = ["ffmpeg", "-v", "error", "-i", path, "-map", f"0:{index}", "-f", "srt"]
        result = await _run(ctx, [*argv, "-y", target], FRAME_TIMEOUT)
        if result.exit_code == 0:  # a track of pictures, as on a DVD, can't be text
            data = await ctx.executor.read_bytes(target)
            label = f" ({language})" if language else ""
            return f"from the subtitle track in the file{label}", data.decode("utf-8", "replace")
    return None


async def _has_whisper(ctx: ToolContext) -> bool:
    try:
        result = await ctx.executor.run(["which", "whisper"], timeout=PROBE_TIMEOUT)
    except FileNotFoundError:
        return False
    return result.exit_code == 0


async def _whisper(
    ctx: ToolContext, path: str, scratch: str, start: float, end: float
) -> tuple[str, str] | None:
    audio = f"{scratch}/audio.wav"
    argv = ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"]
    argv += ["-i", path, "-vn", "-ac", "1", "-ar", "16000", "-y", audio]
    if (await _run(ctx, argv, FRAME_TIMEOUT * 5)).exit_code != 0:
        return None
    argv = ["whisper", audio, "--model", WHISPER_MODEL, "--output_format", "srt"]
    argv += ["--output_dir", scratch, "--fp16", "False", "--verbose", "False"]
    result = await _run(ctx, argv, WHISPER_TIMEOUT)
    if result.exit_code != 0:
        return None
    try:
        data = await ctx.executor.read_bytes(f"{scratch}/audio.srt")
    except OSError:
        return None
    return f"heard by Whisper ({WHISPER_MODEL})", data.decode("utf-8", "replace")


CUE_TIME = re.compile(r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->")
MARKUP = re.compile(r"<[^>]*>|\{\\[^}]*\}")


def parse_cues(text: str) -> list[tuple[float, str]]:
    """(start in seconds, words) for each cue of an SRT or WebVTT file. Captions that roll,
    repeating the cue before's line, as YouTube's do, keep only what's new."""
    cues: list[tuple[float, str]] = []
    previous: set[str] = set()
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        timing = next((n for n, line in enumerate(lines) if CUE_TIME.search(line)), None)
        if timing is None:
            continue
        match = CUE_TIME.search(lines[timing])
        assert match is not None
        at = parse_time(match.group(1).replace(",", "."), "a cue")
        said = [" ".join(MARKUP.sub("", line).split()) for line in lines[timing + 1 :]]
        said = [line for line in said if line]
        new = [line for line in said if line not in previous]
        previous = set(said)
        if new:
            cues.append((at, " ".join(new)))
    return cues
