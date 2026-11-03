"""How long a sandbox takes to run `true`: zwans-jail against Docker.

    python runtime/bench.py jail      # on Linux; from a Mac, through runtime/dev.sh
    python runtime/bench.py docker    # where Docker runs

For the jail, each run is a whole fresh sandbox. For Docker, `exec` is what the Docker
executor does per command (into a container that's already running) and `run` starts a
new container, the closer match to what the jail does.
"""

import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

from zwans.executor.jail import SYSTEM_FOLDERS

RUNS = 50
IMAGE = "zwans-sandbox:0.1"


def timed(command: list[str], stdin: str | None = None) -> tuple[float, str]:
    started = time.perf_counter()
    done = subprocess.run(command, input=stdin, capture_output=True, text=True, check=True)
    return (time.perf_counter() - started) * 1000, done.stderr


def report(name: str, times: list[float]) -> None:
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    median = statistics.median(times)
    print(f"{name:<24} median {median:7.1f} ms   p95 {p95:7.1f} ms   n={len(times)}")


def jail() -> None:
    binary = os.environ.get("ZWANS_JAIL", "runtime/target/release/zwans-jail")
    workspace = tempfile.mkdtemp()
    spec = json.dumps(
        {
            "argv": ["true"],
            "workspace": workspace,
            # The executor's own list: x86-64 needs /lib64 for the dynamic loader, arm64 /lib
            "read_only": [folder for folder in SYSTEM_FOLDERS if os.path.exists(folder)],
            "env": {"PATH": "/usr/bin:/bin"},
        }
    )
    timed([binary], spec)  # warm the page cache
    walls, setups = [], []
    for _ in range(RUNS):
        wall, stderr = timed([binary, "--stats"], spec)
        walls.append(wall)
        setups.append(json.loads(stderr.strip().splitlines()[-1])["setup_ms"])
    report("zwans-jail (wall)", walls)
    report("zwans-jail (setup only)", setups)


def docker() -> None:
    name = f"zwans-bench-{os.getpid()}"
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "--network", "none", IMAGE, "sleep", "600"],
        check=True,
        capture_output=True,
    )
    try:
        timed(["docker", "exec", name, "true"])
        report("docker exec", [timed(["docker", "exec", name, "true"])[0] for _ in range(RUNS)])
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    command = ["docker", "run", "--rm", "--network", "none", IMAGE, "true"]
    report("docker run", [timed(command)[0] for _ in range(20)])


if __name__ == "__main__":
    {"jail": jail, "docker": docker}[sys.argv[1] if len(sys.argv) > 1 else "jail"]()
