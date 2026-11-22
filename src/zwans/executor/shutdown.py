"""Closing a session properly when Zwans is told to quit (SIGTERM) or its terminal is closed
(SIGHUP). Both would otherwise end Zwans at once, skipping the session's cleanup: background
jobs, MCP servers and the Docker container run in groups of their own, so nothing else stops
them, and they'd be left running."""

import asyncio
import contextlib
import os
import signal
import sys
from collections.abc import Callable, Coroutine, Iterator
from contextvars import Context
from types import FrameType
from typing import Any, Self

# Python's own handlers can only be set from the main thread, and Windows has neither signal.
STOP_SIGNALS: tuple[signal.Signals, ...] = ()
if sys.platform != "win32":
    STOP_SIGNALS = (signal.SIGTERM, signal.SIGHUP)

_Handler = Callable[[int, FrameType | None], Any] | int | None

_reading = 0  # blocking reads on the event loop's thread, such as an approval question's


@contextlib.contextmanager
def reading_input() -> Iterator[None]:
    """Mark a blocking read, such as input(), done on the event loop's thread. The loop can't
    run a cancel until the read returns, and Python retries a read a signal interrupted, so a
    stop signal arriving meanwhile cancels from within the read instead."""
    global _reading
    _reading += 1
    try:
        yield
    finally:
        _reading -= 1


# typeshed marks Runner final, but Python doesn't, and this only adds to `run`.
class SessionRunner(asyncio.Runner):  # type: ignore[misc]
    """An `asyncio.Runner` that turns SIGTERM and SIGHUP into `SystemExit`, as Ctrl+C becomes
    KeyboardInterrupt: what's running is cancelled, so `finally` blocks can close the
    session, and the exit code says which signal it was (128 + its number)."""

    def __init__(self) -> None:
        super().__init__()
        self._main: asyncio.Task[Any] | None = None  # what `run` is running now
        self._signal: int | None = None
        self._cancelled = False  # the signal cancelled the current `run`
        self._closing = False  # the session is being closed, which a signal mustn't stop
        self._previous: dict[int, _Handler] = {}

    def __enter__(self) -> Self:
        super().__enter__()
        for sig in STOP_SIGNALS:
            # An ignored signal stays ignored, as SIGHUP is under nohup.
            if signal.getsignal(sig) == signal.SIG_IGN:
                continue
            with contextlib.suppress(ValueError):  # not the main thread, as in some tests
                self._previous[sig] = signal.signal(sig, self._on_signal)
        return self

    def close(self) -> None:
        for sig, handler in self._previous.items():
            signal.signal(sig, handler)
        self._previous.clear()
        super().close()

    def run[T](self, coro: Coroutine[Any, Any, T], *, context: Context | None = None) -> T:
        self._cancelled = False
        try:
            result = super().run(self._track(coro), context=context)
        except asyncio.CancelledError:
            if self._cancelled:
                raise self._exit() from None
            raise
        if self._cancelled:  # the coroutine caught the cancel and returned anyway
            raise self._exit()
        return result

    def run_cleanup[T](self, coro: Coroutine[Any, Any, T]) -> T:
        """Run what closes the session. A stop signal arriving meanwhile doesn't cancel it:
        it's what stops the jobs."""
        self._closing = True
        return self.run(coro)

    async def _track[T](self, coro: Coroutine[Any, Any, T]) -> T:
        self._main = asyncio.current_task()
        try:
            return await coro
        finally:
            self._main = None

    def _on_signal(self, signum: int, frame: FrameType | None) -> None:
        if signum == getattr(signal, "SIGHUP", None):
            _detach_from_terminal()
        if self._closing:
            # Already closing, perhaps because of an earlier signal (the shell passes SIGHUP
            # on too): let the cleanup finish.
            return
        self._signal = signum
        main = self._main
        if main is not None and not main.done():
            self._cancelled = True
            if _reading:
                # The read blocks the loop, so cancel right here: the task stops as if the
                # read had been an `await` that got cancelled.
                main.cancel()
                raise asyncio.CancelledError
            self.get_loop().call_soon_threadsafe(main.cancel)
        else:  # between runs, such as waiting for a line typed without the composer
            raise self._exit()

    def _exit(self) -> SystemExit:
        self._closing = True  # the `finally` that catches it closes the session
        return SystemExit(128 + (self._signal or 0))


def _detach_from_terminal() -> None:
    """The terminal is gone, so send what's printed from now on nowhere: writing to it would
    fail and stop the cleanup."""
    with contextlib.suppress(OSError):
        devnull = os.open(os.devnull, os.O_WRONLY)
        for fd in (1, 2):
            os.dup2(devnull, fd)
        os.close(devnull)
