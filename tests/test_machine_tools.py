"""Ports, Containers, Env and Notify: tools that look at the machine around the project."""

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.containers import ContainersInput, ContainersTool, parse_labels
from zwans.tools.env_vars import EnvInput, EnvTool, is_hidden, settings_names
from zwans.tools.notify import NotifyInput, NotifyTool
from zwans.tools.ports import PortsInput, PortsTool, parse_ss, uptime

SECRET = "zz-very-secret-value-8812"


def run(tool: Any, args: Any, ctx: ToolContext) -> ToolOutput:
    output: ToolOutput = asyncio.run(tool.run(args, ctx))
    return output


def fake_program(folder: Path, name: str, script: str) -> Path:
    """A shell script on PATH standing in for a real program."""
    folder.mkdir(exist_ok=True)
    path = folder / name
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return path


@pytest.fixture
def bin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A folder of fake programs, first on PATH."""
    folder = tmp_path.parent / f"{tmp_path.name}-bin"
    folder.mkdir()
    monkeypatch.setenv("PATH", f"{folder}{os.pathsep}{os.environ['PATH']}")
    return folder


# -- Ports


def lsof_script(bin_dir: Path, workspace: Path) -> None:
    listen = bin_dir / "listen.txt"
    listen.write_text(
        "\n".join(
            [
                # a dev server in the workspace, on IPv4 and IPv6
                "p4100",
                "cnode",
                "f20",
                "PTCP",
                "n*:3000",
                "TST=LISTEN",
                "f21",
                "PTCP",
                "n[::]:3000",
                "TST=LISTEN",
                # postgres, localhost only, with a worker sharing the socket
                "p200",
                "cpostgres",
                "f5",
                "PTCP",
                "n127.0.0.1:5432",
                "TST=LISTEN",
                "f6",
                "PTCP",
                "n[::1]:5432",
                "TST=LISTEN",
                "p201",
                "cpostgres",
                "f5",
                "PTCP",
                "n127.0.0.1:5432",
                "TST=LISTEN",
                # something bound to one address
                "p300",
                "cpython3",
                "f3",
                "PTCP",
                "n192.168.1.20:8000",
                "TST=LISTEN",
            ]
        )
        + "\n"
    )
    cwd = bin_dir / "cwd.txt"
    cwd.write_text(f"p4100\nfcwd\nn{workspace}/web\np200\nfcwd\nn/usr/local/var\n")
    fake_program(
        bin_dir,
        "lsof",
        f'case "$*" in *cwd*) /bin/cat "{cwd}";; *LISTEN*) /bin/cat "{listen}";; esac\n',
    )
    long_command = "python3 -m http.server 8000 " + "--flag " * 40
    fake_program(
        bin_dir,
        "ps",
        "printf '%s\\n' "
        "' 4100     1    01:02:03 node server.js --port 3000' "
        "'  200     1 3-04:05:06 /usr/local/bin/postgres -D /usr/local/var/postgres' "
        "'  201   200    00:42 postgres: checkpointer' "
        f"'  300     1    05:07 {long_command}'\n",
    )


def test_ports_lists_one_row_per_port_with_this_projects_first(
    tmp_path: Path, ctx: ToolContext, bin_dir: Path
) -> None:
    lsof_script(bin_dir, tmp_path)
    output = run(PortsTool(), PortsInput(), ctx).content
    lines = output.splitlines()
    assert lines[0] == "3 TCP ports listening, 1 from this project (listed first)."
    assert lines[1].split() == ["PORT", "ADDRESS", "PID", "UP", "FOLDER", "COMMAND"]
    assert lines[2].startswith("3000  all interfaces  4100  1h 2m")
    assert "this project: web" in lines[2]
    assert "node server.js --port 3000" in lines[2]
    postgres = next(line for line in lines if line.startswith("5432"))
    assert "localhost only" in postgres and " 200 " in postgres and "3d 4h" in postgres
    assert "(+1 more process on it)" in postgres
    assert "/usr/local/var" in postgres
    bound = next(line for line in lines if line.startswith("8000"))
    assert "192.168.1.20" in bound and "5m 7s" in bound
    assert "…" in bound and len(bound) < 250  # the command line is capped
    assert sum(1 for line in lines if line.startswith("3000")) == 1  # IPv4 and IPv6 are one
    assert "kill <pid>" in output


def test_ports_for_one_port_says_whether_it_is_free(
    tmp_path: Path, ctx: ToolContext, bin_dir: Path
) -> None:
    lsof_script(bin_dir, tmp_path)
    used = run(PortsTool(), PortsInput(port=5432), ctx).content
    assert "5432" in used and "3000" not in used
    free = run(PortsTool(), PortsInput(port=8080), ctx).content
    assert free.startswith("Nothing is listening on TCP port 8080; it's free.")


def test_ss_output_and_elapsed_times_are_read() -> None:
    listeners = parse_ss(
        'LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:* users:(("systemd-resolve",pid=612,fd=14))\n'
        'LISTEN 0 128 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=900,fd=3))\n'
        'LISTEN 0 128 [::]:22 [::]:* users:(("sshd",pid=900,fd=4))\n'
        "LISTEN 0 511 *:8080 *:*\n"
    )
    assert [(item.port, item.pids, item.program) for item in listeners] == [
        (22, [900], "sshd"),
        (53, [612], "systemd-resolve"),
        (8080, [], ""),
    ]
    assert listeners[0].hosts == {"0.0.0.0", "::"}
    assert listeners[1].hosts == {"127.0.0.53"}
    assert [uptime(t) for t in ("00:09", "12:01", "02:03:04", "16-04:18:35", "x")] == [
        "9s",
        "12m 1s",
        "2h 3m",
        "16d 4h",
        "x",
    ]


# -- Containers


def docker_script(bin_dir: Path, workspace: Path) -> None:
    ours = {
        "ID": "aaa111",
        "Image": "postgres:16",
        "Names": "app-db-1",
        "State": "running",
        "Status": "Up 2 hours (healthy)",
        "Ports": "0.0.0.0:5433->5432/tcp, [::]:5433->5432/tcp",
        "Labels": "com.docker.compose.project=app,com.docker.compose.service=db,"
        "com.docker.compose.project.config_files=/x/a.yml,/x/b.yml,"
        f"com.docker.compose.project.working_dir={workspace}",
    }
    other = {
        "ID": "bbb222",
        "Image": "redis:7",
        "Names": "elsewhere-redis-1",
        "State": "exited",
        "Status": "Exited (137) 2 days ago",
        "Ports": "",
        "Labels": "com.docker.compose.project=elsewhere,com.docker.compose.service=redis,"
        "com.docker.compose.project.working_dir=/somewhere/else",
    }
    (bin_dir / "ps.txt").write_text(json.dumps(other) + "\n" + json.dumps(ours) + "\n")
    inspected = [
        {
            "Id": "bbb222ccc333ddd",
            "Name": "/elsewhere-redis-1",
            "RestartCount": 4,
            "State": {
                "Status": "exited",
                "Running": False,
                "OOMKilled": True,
                "ExitCode": 137,
                "StartedAt": "2026-11-20T10:00:00.123456789Z",
                "FinishedAt": "2026-11-22T11:00:00.5Z",
                "Health": {
                    "Status": "unhealthy",
                    "FailingStreak": 3,
                    "Log": [
                        {"End": "2026-11-22T10:59:00.1Z", "ExitCode": 1, "Output": "no\nreply"}
                    ],
                },
            },
            "Config": {
                "Image": "redis:7",
                "Env": [f"REDIS_PASSWORD={SECRET}", "PATH=/usr/bin"],
                "Labels": {"com.docker.compose.project": "elsewhere"},
            },
            "NetworkSettings": {
                "Ports": {"6379/tcp": [{"HostIp": "127.0.0.1", "HostPort": "6380"}]}
            },
            "Mounts": [{"Type": "volume", "Name": "redisdata", "Destination": "/data", "RW": True}],
        }
    ]
    (bin_dir / "inspect.txt").write_text(json.dumps(inspected))
    fake_program(
        bin_dir,
        "docker",
        f"""case "$1" in
ps) /bin/cat "{bin_dir}/ps.txt";;
inspect)
  case "$*" in *elsewhere-redis-1*) /bin/cat "{bin_dir}/inspect.txt";;
  *) echo "Error: No such container: $4" >&2; exit 1;; esac;;
logs)
  printf '2026-11-22T10:58:00.000000001Z \\033[32mReady to accept connections\\033[0m\\n'
  printf '2026-11-22T10:58:30.2Z WARNING memory overcommit\\n' >&2
  printf '2026-11-22T10:59:00.3Z Bye\\n';;
esac
""",
    )


def test_containers_lists_this_projects_first_with_compose_names(
    tmp_path: Path, ctx: ToolContext, bin_dir: Path
) -> None:
    docker_script(bin_dir, tmp_path)
    output = run(ContainersTool(), ContainersInput(), ctx).content
    lines = output.splitlines()
    assert lines[0] == "2 containers (1 running), from docker:"
    assert lines[1].split() == ["NAME", "IMAGE", "STATUS", "PORTS", "COMPOSE"]
    assert lines[2].startswith("app-db-1")
    assert "Up 2 hours (healthy)" in lines[2]
    assert ":5433->5432/tcp  app/db (this project)" in lines[2]
    assert "[::]" not in lines[2]  # the IPv6 twin of the mapping is dropped
    assert lines[3].startswith("elsewhere-redis-1") and lines[3].endswith("elsewhere/redis")


def test_one_container_shows_its_state_and_logs_but_no_env_values(
    tmp_path: Path, ctx: ToolContext, bin_dir: Path
) -> None:
    docker_script(bin_dir, tmp_path)
    output = run(ContainersTool(), ContainersInput(container="elsewhere-redis-1"), ctx).content
    assert SECRET not in output
    assert "Container elsewhere-redis-1 (bbb222ccc333), image redis:7" in output
    assert "State: exited, exit code 137, stopped 2026-11-22T11:00:00Z" in output
    assert "restarted 4 times" in output
    assert "killed for running out of memory" in output
    assert "Health: unhealthy, failing streak 3" in output
    assert "2026-11-22T10:59:00Z  exit 1  no | reply" in output
    assert "Ports: 6379/tcp -> 127.0.0.1:6380" in output
    assert "volume redisdata -> /data (rw)" in output
    assert "PATH, REDIS_PASSWORD" in output
    logs = output.split("Last 3 log lines:\n", 1)[1].splitlines()
    assert logs == [
        "2026-11-22T10:58:00Z Ready to accept connections",
        "2026-11-22T10:58:30Z WARNING memory overcommit",
        "2026-11-22T10:59:00Z Bye",
    ]


def test_containers_says_when_the_daemon_is_off_or_a_name_is_wrong(
    tmp_path: Path, ctx: ToolContext, bin_dir: Path
) -> None:
    docker_script(bin_dir, tmp_path)
    with pytest.raises(ToolError, match="No container is named 'nope'"):
        run(ContainersTool(), ContainersInput(container="nope"), ctx)
    fake_program(
        bin_dir,
        "docker",
        "echo 'Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
        "Is the docker daemon running?' >&2; exit 1\n",
    )
    with pytest.raises(ToolError, match="daemon isn't running"):
        run(ContainersTool(), ContainersInput(), ctx)


def test_docker_labels_with_commas_in_values_are_read() -> None:
    labels = parse_labels("a=1,files=/x/a.yml,/x/b.yml,deps=redis:ok:false,db:ok:false,b=")
    assert labels == {
        "a": "1",
        "files": "/x/a.yml,/x/b.yml",
        "deps": "redis:ok:false,db:ok:false",
        "b": "",
    }
    assert parse_labels({"k": "v"}) == {"k": "v"}


# -- Env


def make_project(root: Path) -> None:
    files = {
        "app.py": (
            "import os\n"
            'URL = os.environ["DATABASE_URL"]\n'
            'PORT = os.getenv("PORT", "8000")\n'
            'DEBUG = os.environ.get("DEBUG")\n'
            'HOME = os.environ["HOME"]\n'
        ),
        "web/client.ts": (
            "const token = process.env.API_TOKEN;\n"
            "const timeout = process.env.TIMEOUT ?? 30;\n"
            'const base = import.meta.env.VITE_BASE || "/";\n'
        ),
        "src/main.rs": 'let key = std::env::var("RUST_KEY").unwrap();\n',
        "cmd/main.go": 'region := os.Getenv("GO_REGION")\n',
        "lib/app.rb": 'key = ENV.fetch("RUBY_KEY", "dev")\nother = ENV["RUBY_OTHER"]\n',
        "docker-compose.yml": (
            "services:\n  db:\n    environment:\n"
            "      POSTGRES_PASSWORD: ${PG_PASSWORD:?set it}\n"
            "      PGPORT: ${PG_PORT:-5432}\n"
        ),
        "settings.py": (
            "from pydantic_settings import BaseSettings, SettingsConfigDict\n"
            "class Settings(BaseSettings):\n"
            '    model_config = SettingsConfigDict(env_prefix="APP_")\n'
            "    name: str\n"
            "    level: int = 3\n"
        ),
        ".env.example": "# copy to .env\nDATABASE_URL=\nEXAMPLE_ONLY=changeme\n",
        ".env": f"API_TOKEN={SECRET}\nexport DATABASE_URL={SECRET}\n",
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def test_env_lists_names_where_they_are_used_and_never_values(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_project(tmp_path)
    for name in ("DATABASE_URL", "PORT", "DEBUG", "RUST_KEY", "PG_PASSWORD", "APP_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("API_TOKEN", SECRET)
    monkeypatch.setenv("GO_REGION", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)  # Zwans's own: never passed on

    output = run(EnvTool(), EnvInput(), ctx).content
    assert SECRET not in output
    missing, rest = output.split("Set in the environment commands run in", 1)
    present, defaults = rest.split("Not set, but the code has a default", 1)
    row = {line.split()[0]: line for line in output.splitlines() if line.startswith("  ")}

    for name in ("DATABASE_URL", "DEBUG", "RUST_KEY", "RUBY_OTHER", "PG_PASSWORD", "APP_NAME"):
        assert f"  {name}" in missing, name
    assert "  API_TOKEN" in present and "  GO_REGION" in present
    for name in ("PORT", "TIMEOUT", "VITE_BASE", "RUBY_KEY", "PG_PORT", "APP_LEVEL"):
        assert f"  {name}" in defaults, name

    assert ".env.example:2, app.py:2" in row["DATABASE_URL"]
    assert "in .env" in row["DATABASE_URL"]
    assert "web/client.ts:1" in row["API_TOKEN"] and "in .env" in row["API_TOKEN"]
    assert "only in the example file" in row["EXAMPLE_ONLY"]
    assert "settings.py:4" in row["APP_NAME"]
    assert "docker-compose.yml:5" in row["PG_PORT"]
    assert "HOME" not in row and "Left out common system names: HOME." in output
    assert "WARNING" not in output  # not a git repository


def test_env_warns_when_dotenv_is_tracked_by_git(tmp_path: Path, ctx: ToolContext) -> None:
    if shutil.which("git") is None:
        pytest.skip("git isn't installed")
    make_project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", ".env"], cwd=tmp_path, check=True)
    output = run(EnvTool(), EnvInput(), ctx).content
    assert "WARNING: .env is tracked by git" in output
    assert SECRET not in output


def test_env_files_the_policy_hides_are_not_read(
    tmp_path: Path, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_project(tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "keys.py").write_text('KEY = os.environ["HIDDEN_KEY"]\n')
    monkeypatch.delenv("DATABASE_URL", raising=False)
    asked: list[str] = []

    def hidden(search: str) -> list[str]:
        asked.append(search)
        return [".env", "secrets/**"]

    output = run(EnvTool(hidden=hidden), EnvInput(), ctx).content
    assert asked == ["."]
    assert SECRET not in output
    assert "in .env" not in output  # .env wasn't read
    assert "The policy keeps .env from being read" in output
    assert ".env.local" not in output  # there is none
    assert "HIDDEN_KEY" not in output  # nor was the hidden folder searched
    assert "DATABASE_URL" in output and "API_TOKEN" in output  # the code still was

    plain = run(EnvTool(), EnvInput(), ctx).content
    assert "HIDDEN_KEY" in plain and "in .env" in plain and "The policy keeps" not in plain


def test_hidden_globs_are_read_like_ripgrep_reads_them() -> None:
    assert is_hidden(".env", [".env"])
    assert is_hidden("app/.env", [".env"])  # no slash: a name at any depth
    assert not is_hidden("app/.env", ["/.env"])  # anchored to the root
    assert is_hidden(".env.local", [".env*"])
    assert is_hidden("config/prod/.ENV", ["config/**/.env"])
    assert is_hidden("secrets/a/b.txt", ["secrets/"])  # a folder hides what's in it
    assert not is_hidden("app/.envrc", [".env"])
    assert is_hidden("x[1].env", [r"x\[1\].env"])  # the policy's escapes are undone


def test_pydantic_settings_fields_aliases_and_inherited_classes() -> None:
    source = (
        "from pydantic import Field\n"
        "from pydantic_settings import BaseSettings\n"
        "class Base(BaseSettings):\n"
        "    class Config:\n"
        '        env_prefix = "svc_"\n'
        "    host: str = 'localhost'\n"
        "    _private: int = 1\n"
        "class App(Base):\n"
        '    token: str = Field(alias="SERVICE_TOKEN")\n'
        "    retries: int = Field(5)\n"
        "    url: str = Field(...)\n"
    )
    assert settings_names(source) == [
        ("SVC_HOST", 6, True),
        ("SERVICE_TOKEN", 9, False),
        ("RETRIES", 10, True),
        ("URL", 11, False),
    ]


# -- Notify


def test_notify_passes_the_text_as_arguments_not_as_a_script(
    ctx: ToolContext, bin_dir: Path
) -> None:
    record = bin_dir / "argv.txt"
    fake_program(bin_dir, "osascript", f'printf \'%s\\n\' "$@" > "{record}"\n')
    message = 'Tests passed: "all" \\ 42 -- done" & do shell script "echo hi'
    output = run(NotifyTool(), NotifyInput(message=message, title="Zwans"), ctx)
    assert output.content == f"Notified: Zwans: {message}"
    argv = record.read_text().splitlines()
    assert argv[-3:] == ["--", message, "Zwans"]
    assert "display notification (item 1 of argv) with title (item 2 of argv)" in argv
    assert not any(message in arg for arg in argv[:-2])


def test_notify_uses_notify_send_without_osascript_and_says_when_neither_exists(
    ctx: ToolContext, bin_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = bin_dir / "argv.txt"
    fake_program(bin_dir, "notify-send", f'printf \'%s\\n\' "$@" > "{record}"\n')
    monkeypatch.setenv("PATH", str(bin_dir))
    run(NotifyTool(), NotifyInput(message="Build finished"), ctx)
    assert record.read_text().splitlines() == ["--app-name=Zwans", "--", "Zwans", "Build finished"]
    (bin_dir / "notify-send").unlink()
    with pytest.raises(ToolError, match="aren't supported here"):
        run(NotifyTool(), NotifyInput(message="Build finished"), ctx)
