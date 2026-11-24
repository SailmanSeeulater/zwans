import asyncio
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from zwans.executor.local import LocalExecutor
from zwans.policy.engine import Permissions
from zwans.policy.rules import Decision, Policy, PolicyFile
from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.video import VideoInput, VideoTool, clock, parse_cues, parse_time

needs_ffmpeg = pytest.mark.skipif(
    not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="needs ffmpeg"
)

SUBS = """1
00:00:00,500 --> 00:00:02,000
Hello <i>there</i>.

2
00:00:03,000 --> 00:00:05,000
{\\an8}Second line.
"""


def run(ctx: ToolContext, path: str, **args: object) -> ToolOutput:
    return asyncio.run(VideoTool().run(VideoInput.model_validate({"path": path, **args}), ctx))


@pytest.fixture(scope="module")
def clips(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A 6-second clip with sound and a subtitle track, and one with neither."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("needs ffmpeg")
    folder = tmp_path_factory.mktemp("clips")
    (folder / "subs.srt").write_text(SUBS)
    ffmpeg = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i"]
    picture = "testsrc=duration=6:size=320x240:rate=10"
    talk = [*ffmpeg, picture, "-f", "lavfi", "-i", "sine=duration=6", "-i", "subs.srt"]
    talk += ["-map", "0", "-map", "1", "-map", "2", "-c:v", "mpeg4", "-c:a", "aac"]
    talk += ["-c:s", "mov_text", "-metadata:s:s:0", "language=eng", "talk.mp4"]
    subprocess.run(talk, cwd=folder, check=True)
    subprocess.run([*ffmpeg, picture, "-c:v", "mpeg4", "quiet.mp4"], cwd=folder, check=True)
    return folder


@pytest.fixture
def workspace(tmp_path: Path, clips: Path) -> Path:
    for name in ("talk.mp4", "quiet.mp4"):
        shutil.copy(clips / name, tmp_path / name)
    return tmp_path


# -- times and cues


def test_times_are_read_and_written_the_usual_ways() -> None:
    assert [parse_time(t, "start") for t in ("90", "1:30", "1:02:03", "0:01.5")] == [
        90,
        90,
        3723,
        1.5,
    ]
    for bad in ("soon", "1:2:3:4", "-5", ""):
        with pytest.raises(ToolError, match='start should be a time such as "1:30"'):
            parse_time(bad, "start")
    assert [clock(s) for s in (0, 65.9, 3723)] == ["0:00", "1:05", "1:02:03"]


def test_cues_come_from_srt_and_rolling_webvtt() -> None:
    assert parse_cues(SUBS) == [(0.5, "Hello there."), (3.0, "Second line.")]
    rolling = """WEBVTT

00:00:01.000 --> 00:00:03.000 align:start
<c>so</c> the first

00:00:03.000 --> 00:00:05.000
so the first
and then more
"""
    assert parse_cues(rolling) == [(1.0, "so the first"), (3.0, "and then more")]


# -- watching


@needs_ffmpeg
def test_frames_come_as_one_image_with_their_times_and_the_subtitles(
    workspace: Path, ctx: ToolContext
) -> None:
    output = run(ctx, "talk.mp4", frames=3)

    lines = output.content.splitlines()
    assert lines[0] == "talk.mp4: 0:06, 320x240, 10 fps, mpeg4, with sound, 1 subtitle track"
    assert lines[1] == (
        "3 frames from 0:00 to 0:06, left to right and top to bottom: 1 at 0:01, 2 at 0:03, "
        "3 at 0:05."
    )
    (image,) = output.images
    assert image.source.media_type == "image/jpeg"
    assert "Transcript (from the subtitle track in the file (eng)):" in output.content
    assert "[0:00] Hello there.\n[0:03] Second line." in output.content
    assert sorted(p.name for p in workspace.iterdir()) == ["quiet.mp4", "talk.mp4"]  # no scratch


@needs_ffmpeg
def test_a_range_narrows_the_frames_and_the_transcript(workspace: Path, ctx: ToolContext) -> None:
    (workspace / "talk.srt").write_text(SUBS.replace("Second", "Beside"))
    output = run(ctx, "talk.mp4", start="0:02.5", end="5", frames=1)

    assert "The frame at 0:03." in output.content
    assert output.images[0].source.media_type == "image/png"
    assert "Transcript (from talk.srt):\n[0:03] Beside line." in output.content  # beside wins
    assert "Hello" not in output.content

    only_words = run(ctx, "talk.mp4", frames=0)
    assert only_words.images == () and "[0:00] Hello there." in only_words.content


@needs_ffmpeg
def test_without_subtitles_it_says_why_or_asks_whisper(
    workspace: Path,
    ctx: ToolContext,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quiet = run(ctx, "quiet.mp4", frames=0)
    assert quiet.content.endswith("No transcript: the video has no sound and no subtitles.")

    bin_dir = tmp_path_factory.mktemp("bin")
    whisper = bin_dir / "whisper"
    # Writes what Whisper would, times counted from the start of the audio it was given.
    whisper.write_text(
        "#!/bin/sh\n"
        'out=""; while [ $# -gt 0 ]; do [ "$1" = --output_dir ] && out="$2"; shift; done\n'
        'printf "1\\n00:00:01,000 --> 00:00:02,000\\nHeard it.\\n" > "$out/audio.srt"\n'
    )
    whisper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    # Sound, but no subtitles.
    voice = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=duration=6"]
    voice += ["-f", "lavfi", "-i", "sine=duration=6", "-c:v", "mpeg4", "-c:a", "aac"]
    subprocess.run([*voice, str(workspace / "voice.mp4")], check=True)
    heard = run(ctx, "voice.mp4", start="2", frames=0)
    assert "Transcript (heard by Whisper (base)):\n[0:03] Heard it." in heard.content


@needs_ffmpeg
def test_problems_are_explained(workspace: Path, ctx: ToolContext) -> None:
    with pytest.raises(ToolError, match=r"There is no missing\.mp4"):
        run(ctx, "missing.mp4")
    (workspace / "notes.txt").write_text("not a video")
    with pytest.raises(ToolError, match=r"notes\.txt couldn't be read as a video: "):
        run(ctx, "notes.txt")
    with pytest.raises(ToolError, match=r"between 0:10 and 0:06: talk\.mp4 is 0:06 long"):
        run(ctx, "talk.mp4", start="0:10")
    with pytest.raises(ToolError, match="end should be a time"):
        run(ctx, "talk.mp4", end="later")


def test_a_rule_about_reading_a_file_covers_watching_it(tmp_path: Path) -> None:
    policy = Policy.default()
    policy.add(PolicyFile(mode="auto", deny=["Read(secret/**)"]), "test")
    executor = LocalExecutor(tmp_path)
    permissions = Permissions(policy, lambda path: True, executor.relative, root=executor.root)

    assert permissions.check(VideoTool(), {"path": "secret/call.mp4"}).decision == Decision.DENY
    assert permissions.check(VideoTool(), {"path": "talk.mp4"}).decision == Decision.ALLOW
