"""Copy the buggy-calc example to a temporary folder and let Zwans fix its failing test.

python examples/run_demo.py             # the real model; needs a credential, costs cents
python examples/run_demo.py --scripted  # replays a scripted model; free and offline
"""

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent


def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="zwans-demo-"))
    shutil.copytree(EXAMPLES / "buggy-calc", workspace, dirs_exist_ok=True)
    # Put this Python first on PATH, so the agent's `python -m pytest` finds pytest.
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}"}

    command = [sys.executable, "-m", "zwans", "run", "make the tests pass", "-w", str(workspace)]
    if "--scripted" in sys.argv[1:]:
        command += ["--fake-script", str(EXAMPLES / "buggy-calc.script.json")]
    subprocess.run(command, env=env)

    check = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    print("\nChecking the result independently:", flush=True)
    return subprocess.run(check, cwd=workspace, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
