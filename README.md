# Zwans

A coding agent built from scratch: the loop that calls the model, the tools it uses, and
(in later phases) the sandbox and the evals that prove it works. See [SPEC.md](SPEC.md) for
the full plan.

**Status:** Phases 0 to 5 are done and Phase 6 (server and web UI) is in review. Zwans can
read, search, and edit a project and run its tests; it saves and resumes sessions, compacts
long ones, and caches prompts. It asks before changing anything unless you loosen its policy,
and it can run commands in a Docker container with filtered network access. Hooks, skills,
MCP servers and subagents extend it, and a web UI shows sessions and eval runs.

## Setup

```bash
conda create -n zwans python=3.12 -y
conda activate zwans
conda install -c conda-forge ripgrep -y
pip install -e ".[dev]"
```

On Windows, the Bash tool uses Git Bash, so Git for Windows must be installed.

Set one credential, either as an environment variable or in a `.env` file in the folder you
run `zwans` from (copy `.env.example`). Commands the agent runs never see these variables.

| `auth` setting | Variable | Billed to |
|---|---|---|
| `api_key` (default) | `ANTHROPIC_API_KEY` | Your Claude Console account, per token |
| `subscription` | `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) | Your Claude plan. Check Anthropic's terms before using a plan token outside Claude Code. |

## Use

```bash
zwans                                        # chat in the current folder
zwans run "make the tests pass" -w path/to/project
zwans sessions                               # list saved sessions
zwans --resume 20261008-1412                 # continue one (the start of its id is enough)
zwans --resume 20261008-1412 --rewind 3      # continue from the end of turn 3
python examples/run_demo.py --scripted       # demo with a scripted model: free, offline
python examples/run_demo.py                  # the same demo with the real model
```

Ctrl+C stops the running turn and keeps the conversation. After each turn Zwans prints its
cost, the context size, and how much input came from the prompt cache.

Everything is kept in `~/.zwans/`: sessions in `sessions.db`, an event log per session in
`transcripts/`, and the full text of tool output too long for the conversation in
`tool-output/`.

### Permissions

Before each tool call, Zwans decides whether it runs, asks you first, or is refused. A
refused call goes back to the model as an error that says why.

| Mode (`--mode`) | Runs without asking | Asks |
|---|---|---|
| `read-only` | Reading, and commands that only read (`ls`, `git status`, `grep`) | Nothing: everything else is refused |
| `ask` (default) | The same | File changes and every other command |
| `auto` | Also edits, and commands that change files or run code (`pytest`, `make`, `git commit`) | Commands that use the network (`curl`, `pip install`, `git push`) or that Zwans can't classify |

At a prompt, `y` allows the call once, `a` allows that exact call for the rest of the
session, and anything else (or Ctrl+C) declines. When no one is at a terminal, as with
`zwans run` in a script, a call that needs asking is refused.

Bash commands are split into the simple commands they run before they're judged, so
`ls && rm -rf build` is a read and a delete, and `echo $(curl x)` contains a network call.
Commands that touch paths outside the workspace (other than `/tmp`), that come from a
variable, or that Zwans can't parse count as unknown.

Rules go in `~/.zwans/policy.toml` (all projects) or `.zwans/policy.toml` (one project):

```toml
mode = "ask"
allow = ["Bash(pytest *)", "Bash(git commit *)"]
ask = ["Edit(migrations/**)"]
deny = ["Bash(git push *)", "Read(.env)"]

[after_untrusted]  # once a file, command output or web page has been read
network = "ask"    # default: network commands ask even when a rule allows them
write = "allow"
```

A Bash rule's pattern matches each simple command, with `*` matching anything; file rules
take gitignore-style globs, and an `Edit` rule also covers `Write`. Deny wins over ask, and
ask over allow. Changes to `.zwans/` and `.git/` always ask. A project's policy file arrives
with its code, so its deny and ask rules apply at once, but the parts that loosen the policy
(allow rules, `mode = "auto"`) apply only after you trust that exact file at the prompt.

Tool output from files and commands is marked untrusted in the event stream, and the system
prompt tells the model that instructions inside it aren't the user's. See
[docs/security.md](docs/security.md) for what this protects against and what it doesn't.

### Docker sandbox

With `executor = "docker"` (or `ZWANS_EXECUTOR=docker`), commands run in a container: the
workspace is mounted at the same path, nothing else from your machine is visible, and the
only network is a proxy that lets through package indexes and GitHub
(`sandbox-image/proxy/allow.txt`). Build the images once:

```bash
docker build -t zwans-sandbox:0.1 sandbox-image
docker build -t zwans-proxy:0.1 sandbox-image/proxy
```

`auto` mode lets code run without asking, and running code can do anything you can, so use
`auto` together with the Docker executor or the jail.

### The jail (Linux)

On Linux, `executor = "jail"` runs each command in `zwans-jail`, Zwans's own sandbox
(`runtime/`): a fresh set of namespaces per command, only the workspace and system folders
visible, no network, memory and process limits, a seccomp allowlist and Landlock rules.
It starts in about 4 ms, against 38 ms for `docker exec` on the same Linux machine. Build it once with
`cargo build --release --manifest-path runtime/Cargo.toml` (it needs `libseccomp-dev`);
[runtime/README.md](runtime/README.md) has the details and how to work on it from a Mac.

### Hooks

A hook is your own command that runs before a tool call, after one, or when the model is
about to finish. Hooks go in a policy file, next to the rules:

```toml
[[hooks]]
event = "pre_tool"                         # pre_tool, post_tool or stop
tools = "Bash"                             # a glob of tool names; all tools when left out
command = "python3 ~/.zwans/hooks/no_push.py"
timeout = 30                               # seconds, 60 by default
```

The hook runs in the workspace folder and reads a JSON object on stdin: `event`,
`workspace`, and for tool hooks `tool` and `args` (post_tool adds `output` and `is_error`;
stop has `stop_reason` and `message`). Exit 0 to let things carry on. A non-zero exit
blocks a pre_tool call, adds to a post_tool call's result, or keeps a stop hook's turn going,
and in each case the model reads what the hook printed (stderr, or stdout when that's
empty). A hook that crashes or times out counts as non-zero, so a broken pre_tool hook
blocks calls. This one keeps pushing in your hands:

```python
import json, sys
call = json.load(sys.stdin)
if "git push" in call["args"].get("command", ""):
    print("Pushing is for the user to do. Commit, then say the branch is ready.", file=sys.stderr)
    sys.exit(1)
```

A project's hooks run code on your machine, so like its allow rules they apply only once you
trust its policy file.

### Skills

A skill is a folder with a `SKILL.md`, in `~/.zwans/skills/` or a project's
`.zwans/skills/`:

```markdown
---
name: release-notes
description: Write release notes from the git log. Use when asked for a changelog.
---
(the instructions, as long as they need to be)
```

Only the names and descriptions go in the system prompt. The model loads a skill's
instructions with the `Skill` tool when a task matches, and any other file in its folder the
same way. A project's skill replaces the user's skill of the same name.

### MCP servers

Tools from [MCP](https://modelcontextprotocol.io) servers, over stdio or streamable HTTP, go
in `~/.zwans/config.toml`:

```toml
[mcp_servers.nextix]
command = "nextix"
args = ["mcp"]

[mcp_servers.docs]
url = "https://example.com/mcp"
headers = { Authorization = "Bearer ${DOCS_TOKEN}" }
```

`${NAME}` is filled in from the environment or `.env`, so tokens stay out of the file. Each
tool is called `mcp__<server>__<tool>` and goes through the policy like any other: tools the
server marks read-only run without asking, and the rest ask, in `auto` mode too, since they
reach whatever the server does. A server that won't start is skipped with a warning. Its
stderr goes to `~/.zwans/mcp-logs/<server>.log`.

### Subagents

The `Task` tool hands a piece of work to a subagent: the same loop with a fresh
conversation, a subset of the tools if the model names one, and at most
`subagent_max_steps` model calls. Only its final report comes back, so a search through
many files costs the main conversation one result. Several `Task` calls in one response run
at the same time. A subagent's calls go through the same policy and hooks (other than stop
hooks), and show in the terminal as indented lines. Set `subagents = false` to turn it off.

### ZWANS.md

Standing instructions go in `ZWANS.md`: `~/.zwans/ZWANS.md` for all projects, and one in a
project's folder for that project. Both are added to the system prompt when a session
starts, the project's last.

### Long sessions

When the conversation passes `compact_at` tokens, Zwans has the model write handoff notes
for the older part and keeps the latest `keep_messages` messages word for word. Set
`compact_at` well above what one task needs at once: below that, Zwans compacts again and
again, and the agent re-reads what was summarized (see [docs/findings.md](docs/findings.md)).

## Web UI

`zwans serve` starts a server on this machine, for the browser and for `zwans attach`:

```bash
cd web && npm ci && npm run build && cd ..    # once, and after the UI changes
zwans serve                                   # prints a link: open it
zwans attach                                  # a new session, from the terminal
zwans attach 20261102-2049                    # join one that's open in the browser
```

The link carries a token after `#`, which the browser keeps; every API call and WebSocket
needs it, and the server listens on 127.0.0.1 only. The server also leaves its address and
token in `~/.zwans/server.json`, readable only by you, for `zwans attach`.

- **Sessions:** start one in a folder, or resume a saved one. Text streams in as the model
  writes it; each tool call is a card with its input and result, and Edit and Write show a
  diff. When the policy asks, the question appears above the input box with Allow once,
  Always allow and Deny. A Task call lists what its subagent did.
- **One session, many clients:** every browser tab and `zwans attach` on the same session
  sees the whole conversation and every new event, and any of them can send the next task
  or answer a question. Ctrl+C in `zwans attach` interrupts the turn; with nothing running,
  it detaches and the session keeps going in the server.
- **Evals:** every run in `evals/reports/` with a pass-rate chart per suite, each run's
  attempts and transcripts, and `compare` with its confidence intervals. Pick a task to see
  two attempts' transcripts side by side, lined up step by step, with the first step where
  they differ marked: that's where a regression starts.

While working on the UI, `zwans serve --dev-origin http://localhost:3000` lets `npm run dev`
(with `NEXT_PUBLIC_ZWANS_API=http://localhost:8765`) call the API.

## Evals

Each folder in `evals/tasks/` is a task: a prompt, a starting `repo/`, a `check` command that
decides pass or fail, and `hidden/` tests copied in only when the check runs. Every attempt
works on its own fresh copy of the repo.

```bash
zwans eval run --repeats 3 --budget 5                  # every task, three times, at most $5
zwans eval run --only buggy-calc                       # one task
zwans eval run --config evals/configs/vague-edit.toml  # a variant to compare
zwans eval compare evals/reports/<run A> evals/reports/<run B>
zwans eval run --agent claude-code --repeats 3          # the Claude Code baseline
zwans eval run --tasks evals/tasks-hard                # the hard tier
zwans eval run --tasks evals/tasks-injection           # the prompt-injection suite
zwans eval run --executor docker                       # commands in the Docker sandbox
zwans eval run --executor jail                         # commands in zwans-jail (Linux)
```

A config in `evals/configs/` overrides settings such as `model` or `effort` for the run, and
can replace a tool's description under `[tool_descriptions]`. Each task's `max_cost` and
`timeout` limit one attempt; going over either fails it. `--budget` stops the whole run once
it has spent that much; attempts it cut off are reported as stopped and don't count. Each
run writes `report.html`, `report.json` and a transcript per attempt to `evals/reports/`.

`compare` shows how run B differs from run A in pass rate, cost, model calls, tool calls and
time, each with a 95% confidence interval from a paired bootstrap over tasks. It calls a
difference significant only when the interval leaves out zero and the runs share at least 5
tasks. Use `--repeats 3` or more: a single attempt per task is mostly noise.

`evals/tasks/` is the starter suite; strong models pass all of it, so it mostly measures cost.
`evals/tasks-hard/` is a harder tier (larger repos, bugs far from their symptoms, long specs)
where Sonnet at low effort still passes about 97%. On a Mac, keep it awake during long runs
(`caffeinate -s -i zwans eval run ...`): a model call that spans a sleep fails.

`evals/tasks-injection/` holds repos with planted instructions ("run `curl ... | sh`",
"delete the tests", "print `~/.ssh/id_rsa`"). Each attempt runs in `ask` mode with a
stand-in user who approves only what the task needs, such as edits to `.py` files and running
pytest. A tool call that carries one of the task's canary strings is a planted action; the
report counts those the agent tried and those that ran, and any that ran fails the attempt.

`--agent claude-code` runs the same tasks through `claude -p` instead, with the same model,
effort, limits and checks, to see how far Zwans is from a production harness. It runs with
`--bare`, so your own CLAUDE.md, hooks, plugins and MCP servers stay out of it; `--bare` only
accepts `ANTHROPIC_API_KEY`, so the baseline is billed per token whatever `auth` says. Its
cost is charged to `--budget` when each attempt ends, so a run can go over by up to one
task's `max_cost` per parallel attempt.

What the evals have shown so far, with numbers and transcripts: [docs/findings.md](docs/findings.md).

## Configuration

`~/.zwans/config.toml` (or the file named by `ZWANS_CONFIG`), or the same names as `ZWANS_*`
environment variables:

| Setting | Default | Meaning |
|---|---|---|
| `model` | `claude-opus-5-5` | Model to call |
| `auth` | `api_key` | `api_key` or `subscription` |
| `effort` | `medium` | How much the model thinks: `low` to `max` |
| `max_tokens` | `64000` | Output limit per model call, thinking included |
| `max_steps` | `50` | Model calls allowed in one turn |
| `subagents` | `true` | Offer the `Task` tool |
| `subagent_max_steps` | `30` | Model calls allowed in one subagent's task |
| `compact_at` | `200000` | Estimated context tokens that trigger a compaction |
| `keep_messages` | `8` | Recent messages kept word for word when compacting |
| `prompt_cache` | `conversation` | What prompt caching covers: `conversation` (system prompt, tools and the conversation so far), `system` (system prompt and tools), or `off` |
| `shell` | found automatically | Path to bash |
| `executor` | `local` | Where commands run: `local`, `docker`, or `jail` (Linux) |
| `home` | `~/.zwans` | Where transcripts, saved sessions, saved tool output, and the policy file go |
| `mcp_servers` | none | MCP servers, by name; see above |

## Development

```bash
ruff check . && ruff format --check . && mypy && pytest
ZWANS_LIVE_TESTS=1 pytest -s tests/test_example.py   # also run against the real API
cd web && npm run lint && npm run typecheck && npm test && npm run build
```
