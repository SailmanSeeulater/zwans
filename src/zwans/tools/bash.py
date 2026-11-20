"""The Bash tool: run a shell command in the workspace, now or in the background. BashOutput
and KillBash look after commands left running in the background."""

from pydantic import BaseModel, Field

from zwans.executor.background import BackgroundJobs, Job, JobError
from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_WAIT = 300  # seconds BashOutput may wait for a job


class BashInput(BaseModel):
    command: str = Field(description="The command to run.")
    timeout: int = Field(
        default=120, ge=1, le=600, description="Seconds to wait before stopping the command."
    )
    run_in_background: bool = Field(
        default=False,
        description="Start it and return at once, leaving it running: for dev servers, "
        "watchers and long builds. Read its output with BashOutput; timeout doesn't apply. "
        "Jobs, and anything they started, are stopped when the session ends, so don't tell "
        "the user a server will keep running afterwards.",
    )


class BashTool:
    name = "Bash"
    description = (
        "Run a shell command with bash in the workspace folder and return its output (stdout "
        "and stderr together) and exit code. Each call starts a new shell, so cd and variables "
        "don't carry over. Long output is shortened in the middle. For files, use Read, Edit, "
        "Write, Glob and Grep instead of cat, sed, find and grep. For a command that keeps "
        "running, such as a dev server, set run_in_background instead of appending &: "
        "anything a command leaves running is stopped when it exits."
    )
    input_model = BashInput
    read_only = False

    async def run(self, args: BashInput, ctx: ToolContext) -> ToolOutput:
        if args.run_in_background:
            jobs = _jobs(ctx)
            try:
                job = await jobs.start(args.command)
            except JobError as exc:
                raise ToolError(str(exc)) from exc
            return ToolOutput(
                content=f"Started in the background as {job.id}. Read its output with "
                f"BashOutput, and stop it with KillBash when it's no longer needed."
            )
        result = await ctx.executor.run_shell(args.command, timeout=args.timeout)
        output = result.output.rstrip() or "(no output)"
        if result.timed_out:
            stopped = f"Stopped after {args.timeout}s because it hadn't finished."
            return ToolOutput(content=f"{output}\n{stopped}", is_error=True)
        return ToolOutput(content=f"{output}\n(exit code {result.exit_code})")


class BashOutputInput(BaseModel):
    job_id: str = Field(description="The job's id, such as bg1.")
    wait: int = Field(
        default=0,
        ge=0,
        le=MAX_WAIT,
        description="Seconds to wait for it to finish first, returning early if it does.",
    )


class BashOutputTool:
    name = "BashOutput"
    description = (
        "Read what a background job (Bash with run_in_background) has printed since you last "
        "looked, and whether it's still running. Set wait to give it time to finish first."
    )
    input_model = BashOutputInput
    read_only = True

    async def run(self, args: BashOutputInput, ctx: ToolContext) -> ToolOutput:
        jobs = _jobs(ctx)
        job = _job(jobs, args.job_id)
        await jobs.wait(job, args.wait)
        output = job.take_new_output().rstrip() or "(no new output)"
        return ToolOutput(content=f"{output}\n({job.id} {job.status()})")


class KillBashInput(BaseModel):
    job_id: str = Field(description="The job's id, such as bg1.")


class KillBashTool:
    name = "KillBash"
    description = "Stop a background job, and everything it started."
    input_model = KillBashInput
    read_only = True  # it only stops what the agent itself started

    async def run(self, args: KillBashInput, ctx: ToolContext) -> ToolOutput:
        jobs = _jobs(ctx)
        job = _job(jobs, args.job_id)
        if job.stopped:
            return ToolOutput(content=f"{job.id} was already stopped.")
        code = job.process.returncode
        await jobs.kill(job)
        if code is None:
            return ToolOutput(content=f"Stopped {job.id}.")
        return ToolOutput(
            content=f"{job.id} had exited with code {code}; stopped anything it left running."
        )


def _jobs(ctx: ToolContext) -> BackgroundJobs:
    if ctx.jobs is None:
        raise ToolError("Background jobs aren't available here; run the command normally.")
    return ctx.jobs


def _job(jobs: BackgroundJobs, job_id: str) -> Job:
    try:
        return jobs.get(job_id)
    except JobError as exc:
        raise ToolError(str(exc)) from exc
