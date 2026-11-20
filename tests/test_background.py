import asyncio
import gc
import os
import signal
import sys
import time
from pathlib import Path

import pytest
from helpers import needs_bash, process_gone

from zwans.executor import background
from zwans.executor.background import BackgroundJobs
from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext, ToolError
from zwans.tools.bash import (
    BashInput,
    BashOutputInput,
    BashOutputTool,
    BashTool,
    KillBashInput,
    KillBashTool,
)

pytestmark = needs_bash


def context(tmp_path: Path) -> ToolContext:
    executor = LocalExecutor(tmp_path)
    return ToolContext(executor=executor, jobs=BackgroundJobs(executor))


async def bash(ctx: ToolContext, command: str) -> str:
    return (await BashTool().run(BashInput(command=command, run_in_background=True), ctx)).content


async def output(ctx: ToolContext, job_id: str, wait: int = 0) -> str:
    return (await BashOutputTool().run(BashOutputInput(job_id=job_id, wait=wait), ctx)).content


def test_a_job_runs_on_and_its_output_is_read_in_pieces(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def go() -> list[str]:
        started = await bash(ctx, "echo first; sleep 1; echo second")
        await asyncio.sleep(0.4)  # time to print the first line
        early = await output(ctx, "bg1")
        done = await output(ctx, "bg1", wait=10)
        again = await output(ctx, "bg1")
        assert ctx.jobs is not None
        await ctx.jobs.close()
        return [started, early, done, again]

    started, early, done, again = asyncio.run(go())

    assert started.startswith("Started in the background as bg1.")
    assert "first" in early and "still running" in early
    assert "second" in done and "first" not in done and "finished with exit code 0" in done
    assert again.startswith("(no new output)")


def test_kill_stops_a_job_and_closing_stops_the_rest(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert ctx.jobs is not None
    jobs = ctx.jobs

    async def go() -> str:
        await bash(ctx, "sleep 60")
        await bash(ctx, "sleep 60")
        killed = await KillBashTool().run(KillBashInput(job_id="bg1"), ctx)
        await jobs.close()
        return killed.content

    assert asyncio.run(go()) == "Stopped bg1."
    assert not any(job.running for job in jobs.jobs.values())


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are a POSIX idea")
def test_killing_a_finished_job_stops_what_it_left_running(tmp_path: Path) -> None:
    ctx = context(tmp_path)

    async def go() -> tuple[str, float, str]:
        await bash(ctx, "sleep 302 & echo $!")
        started = time.monotonic()
        read = await output(ctx, "bg1", wait=10)
        waited = time.monotonic() - started
        killed = await KillBashTool().run(KillBashInput(job_id="bg1"), ctx)
        return read, waited, killed.content

    read, waited, killed = asyncio.run(go())

    assert waited < 3  # the shell's exit, not the sleep holding its output open
    pid, status = read.splitlines()
    assert status == "(bg1 exited with code 0, but something it started is still running)"
    assert killed == "bg1 had exited with code 0; stopped anything it left running."
    assert process_gone(int(pid))


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are a POSIX idea")
def test_closing_stops_what_finished_jobs_left_running(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    assert ctx.jobs is not None
    jobs = ctx.jobs

    async def go() -> str:
        await bash(ctx, "sleep 303 & echo $!")
        read = await output(ctx, "bg1", wait=10)
        await jobs.close()
        again = await KillBashTool().run(KillBashInput(job_id="bg1"), ctx)
        assert again.content == "bg1 was already stopped."
        return read

    assert process_gone(int(asyncio.run(go()).splitlines()[0]))


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are a POSIX idea")
def test_what_a_finished_job_left_running_counts_toward_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(background, "MAX_JOBS", 1)
    ctx = context(tmp_path)
    assert ctx.jobs is not None
    jobs = ctx.jobs

    async def go() -> str:
        await bash(ctx, "sleep 305 & echo $!")
        read = await output(ctx, "bg1", wait=10)
        try:
            with pytest.raises(ToolError, match="1 jobs are already running"):
                await bash(ctx, "sleep 60")
        finally:
            await jobs.close()
        return read

    assert process_gone(int(asyncio.run(go()).splitlines()[0]))


@pytest.mark.skipif(sys.platform == "win32", reason="process groups are a POSIX idea")
def test_killing_a_job_closes_output_held_by_something_that_left_its_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unraisable: list[str] = []
    monkeypatch.setattr(sys, "unraisablehook", lambda info: unraisable.append(repr(info)))
    escape = (
        f"{sys.executable} -c 'import os, time; os.setsid(); print(os.getpid(), flush=True); "
        "time.sleep(30)' & echo started"
    )

    async def go() -> str:
        ctx = context(tmp_path)
        assert ctx.jobs is not None
        await bash(ctx, escape)
        read = await output(ctx, "bg1", wait=10)
        await ctx.jobs.close()
        return read

    read = asyncio.run(go())
    pid = next(int(line) for line in read.splitlines() if line.isdigit())
    os.kill(pid, signal.SIGKILL)  # it left the group, so it's still there
    gc.collect()  # what would otherwise be closed after the event loop, and complain

    assert unraisable == []


def test_old_output_is_dropped_and_said_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background, "KEEP_BYTES", 10)
    ctx = context(tmp_path)

    async def go() -> str:
        await bash(ctx, "printf 0123456789abcdefghij")
        return await output(ctx, "bg1", wait=10)

    text = asyncio.run(go())

    assert text.startswith("[... 10 bytes dropped before they were read ...]\nabcdefghij")


def test_unknown_jobs_and_sessions_without_jobs_are_errors(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="no background job 'bg9'"):
        asyncio.run(output(context(tmp_path), "bg9"))
    with pytest.raises(ToolError, match="aren't available here"):
        asyncio.run(bash(ToolContext(executor=LocalExecutor(tmp_path)), "true"))
