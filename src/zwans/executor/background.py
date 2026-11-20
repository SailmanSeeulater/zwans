"""Background jobs: shell commands that keep running while the agent works, such as a dev
server or a long build. Each runs through the session's executor, so the jail or Docker
contains it like any other command. They're stopped when the session closes, with anything
they left running, such as the server in `server & echo started`."""

import asyncio
import time
from dataclasses import dataclass, field

from zwans.executor.local import LocalExecutor, close_pipes, wait_exit

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
    stopped: bool = False  # by KillBash or the session closing

    @property
    def running(self) -> bool:
        return self.process.returncode is None

    @property
    def left_running(self) -> bool:
        """Whether its shell has exited but something it started still holds its output."""
        open_output = self.pump is not None and not self.pump.done()
        return not self.running and open_output and not self.stopped

    def status(self) -> str:
        if self.running:
            return f"still running after {time.monotonic() - self.started:.0f}s"
        code = self.process.returncode
        if self.left_running:
            return f"exited with code {code}, but something it started is still running"
        return f"finished with exit code {code}"

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
        # A server started as `server & echo started` counts too, though its shell exited.
        running = [job for job in self.jobs.values() if job.running or job.left_running]
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
            # Its exit, not its output closing, which something it left running can hold open.
            await wait_exit(job.process, seconds)
        if not job.running and job.pump is not None:
            # The last of its output. Longer means something it started holds the output open.
            await asyncio.wait([job.pump], timeout=0.5)

    async def kill(self, job: Job) -> None:
        """Stop a job and everything it started, even when its shell has already exited."""
        await self.executor.stop_process(job.process)
        job.stopped = True
        if job.pump is not None:
            done, _ = await asyncio.wait([job.pump], timeout=2)
            if not done:
                # Something that left its process group still holds the output open.
                job.pump.cancel()
                close_pipes(job.process)

    async def close(self) -> None:
        """Stop every job: the session is ending. Finished ones too, since what they left
        running in the background is still in their process group."""
        for job in self.jobs.values():
            if not job.stopped:
                await self.kill(job)


async def _pump(job: Job) -> None:
    stream = job.process.stdout
    assert stream is not None
    while chunk := await stream.read(65536):
        job._feed(chunk)
