"""Background jobs: shell commands that keep running while the agent works, such as a dev
server or a long build. Each runs through the session's executor, so the jail or Docker
contains it like any other command. They're stopped when the session closes."""

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from zwans.executor.local import LocalExecutor

MAX_JOBS = 8
KEEP_BYTES = 1_000_000  # of each job's output; older output is dropped first


class JobError(Exception):
    pass


@dataclass
class Job:
    id: str
    command: str
    process: asyncio.subprocess.Process
    started: float = field(default_factory=time.monotonic)
    output: bytearray = field(default_factory=bytearray)
    dropped: int = 0  # bytes dropped from the front of `output`
    read_to: int = 0  # how far the model has read, counting dropped bytes
    pump: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self.process.returncode is None

    def status(self) -> str:
        if self.running:
            return f"still running after {time.monotonic() - self.started:.0f}s"
        return f"finished with exit code {self.process.returncode}"

    def take_new_output(self) -> str:
        """Output since the last call, noting any that was dropped before it was read."""
        start = max(self.read_to - self.dropped, 0)
        missed = max(self.dropped - self.read_to, 0)
        data = bytes(self.output[start:])
        self.read_to = self.dropped + len(self.output)
        text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
        if missed:
            text = f"[... {missed} bytes dropped before they were read ...]\n{text}"
        return text

    def _feed(self, chunk: bytes) -> None:
        self.output += chunk
        extra = len(self.output) - KEEP_BYTES
        if extra > 0:
            del self.output[:extra]
            self.dropped += extra


class BackgroundJobs:
    def __init__(self, executor: LocalExecutor) -> None:
        self.executor = executor
        self.jobs: dict[str, Job] = {}
        self._count = 0

    async def start(self, command: str) -> Job:
        running = [job for job in self.jobs.values() if job.running]
        if len(running) >= MAX_JOBS:
            raise JobError(f"{len(running)} jobs are already running. Stop one with KillBash.")
        process = await self.executor.start_process(self.executor.shell_argv(command))
        self._count += 1
        job = Job(id=f"bg{self._count}", command=command, process=process)
        job.pump = asyncio.create_task(_pump(job))
        self.jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if job is None:
            known = ", ".join(self.jobs) or "none"
            raise JobError(f"There's no background job {job_id!r}. Jobs: {known}.")
        return job

    async def wait(self, job: Job, seconds: float) -> None:
        """Wait until the job finishes, or `seconds` pass."""
        if job.running and seconds > 0:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(job.process.wait()), seconds)
        if not job.running and job.pump is not None:
            await asyncio.wait([job.pump], timeout=2)  # the last of its output

    async def kill(self, job: Job) -> None:
        await self.executor.stop_process(job.process)
        if job.pump is not None:
            await asyncio.wait([job.pump], timeout=2)
            job.pump.cancel()

    async def close(self) -> None:
        """Stop every job: the session is ending."""
        for job in self.jobs.values():
            if job.running:
                await self.kill(job)
            elif job.pump is not None:
                job.pump.cancel()


async def _pump(job: Job) -> None:
    stream = job.process.stdout
    assert stream is not None
    while chunk := await stream.read(65536):
        job._feed(chunk)
