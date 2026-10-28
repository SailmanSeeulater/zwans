"""The commands jobs can run. Each is a function taking the job's args."""

import subprocess
from collections.abc import Callable

TASKS: dict[str, Callable[[tuple[str, ...]], None]] = {}


def task(
    name: str,
) -> Callable[[Callable[[tuple[str, ...]], None]], Callable[[tuple[str, ...]], None]]:
    def register(function: Callable[[tuple[str, ...]], None]) -> Callable[[tuple[str, ...]], None]:
        TASKS[name] = function
        return function

    return register


@task("shell")
def shell(args: tuple[str, ...]) -> None:
    subprocess.run(list(args), check=True)


@task("echo")
def echo(args: tuple[str, ...]) -> None:
    print(" ".join(args))
