import asyncio
from pathlib import Path

import pytest
from helpers import needs_bash

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
