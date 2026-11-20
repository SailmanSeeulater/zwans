# Zwans

A coding agent built from scratch: the loop that calls the model, the tools it uses, and
(in later phases) the sandbox and the evals that prove it works. See [SPEC.md](SPEC.md) for
the full plan.

**Status:** Phases 0 to 5 are done and Phase 6 (server and web UI) is in review. Zwans can
read, search, and edit a project and run its tests; it saves and resumes sessions, compacts
long ones, and caches prompts. It asks before changing anything unless you loosen its policy,
and it can run commands in a Docker container with filtered network access. It reads `CLAUDE.md`
and `AGENTS.md` and Claude Code's skills, searches and reads the web, and keeps a to-do list
for long tasks. Hooks, skills, MCP servers and subagents extend it, and a web UI shows sessions and eval runs.

## Setup

```bash
conda create -n zwans python=3.12 -y
conda activate zwans
conda install -c conda-forge ripgrep -y
pip install -e ".[dev]"
```

On Windows, the Bash tool uses Git Bash, so Git for Windows must be installed.

### Install as a command

To use Zwans in any project, as you would Claude Code, install it as a tool with
[uv](https://docs.astral.sh/uv/). It gets its own environment, and `zwans` goes on your PATH:

```bash
cd web && npm ci && npm run build && cd ..   # the web UI, which goes into the install
uv tool install .                            # from this checkout
brew install ripgrep                         # Grep and Glob need rg: apt, winget or scoop elsewhere
```

After pulling changes, run `uv tool install --reinstall .` (and rebuild the UI first if it
changed). Skipping the UI build still installs everything else; `zwans serve` then shows a
note instead of the UI.

### Credentials

Set one credential, either as an environment variable, in a `.env` file in the folder you
run `zwans` from (copy `.env.example`), or in `~/.zwans/.env`, which works in every project.
A variable you set wins over both files, and the folder's `.env` over the one in `~/.zwans`.
Commands the agent runs never see these variables.

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

Ctrl+C stops the running turn and keeps the conversation, including what the model had
written so far, marked as cut off. After each turn Zwans prints its cost, the context size,
and how much input came from the prompt cache.

A session is saved as soon as you send something, and one you close without sending anything
isn't kept. `zwans sessions` shows each one's turns, cost, folder and first message. A session
keeps its model, whether chosen with `--model` or `/model`, and its folder: `--resume` says so
when `-w` names another one, and works in the session's folder. A model Zwans doesn't know,
given with `--resume <id> --model <name>`, is kept only once it has answered, so a typo doesn't
stick to the session. A turn that fails before the model
answers, such as on an API error, is taken back, and in the chat your message goes back into
the input to send again. `--rewind` only drops turns from the conversation and leaves the
files as they are; `/rewind` and `/undo` in the chat put the files back too.

In a terminal, the model's answers are shown as markdown (headings, lists, tables, code), a
block at a time, and a status line under the output says what's running and for how long.
Each tool call gets one line, with its result under it: an Edit or Write shows its diff, a
command shows the last few lines of its output and its exit code, and a search or fetch
shows what it found. Piped to a file, the output is plain text.

In the chat, Enter sends and Esc then Enter (or Ctrl+J) starts a new line; pasted text keeps
its lines. Up and Down go through earlier messages, kept in `~/.zwans/history`. Ctrl+C clears
what you've typed, and Ctrl+D quits. A line under the prompt shows the model, the mode, the
context size and the session's cost so far, then key hints; in a narrow terminal the hints go
first, then the end of the status, so the line never wraps. What you type while a turn runs isn't shown; it
waits for the prompt, and each line of it is then sent as its own message, while a paste goes
as one. Ctrl+C drops it along with the turn. When Zwans asks you to approve a tool call,
only what you type after the question answers it. Resuming a session in the chat shows its
last three turns again.

Write `@path` to send a file's text along with the message, or a folder's listing, so the
model doesn't spend a step reading it; Tab completes the path. Files over 100,000 characters
are left for the model to read in parts.

`@path` to a PNG, JPEG, GIF or WebP image sends the image itself, so you can ask about a
screenshot or a design. The model can look at images too: its Read tool shows it an image
file instead of refusing it. Images can be up to 3.75 MB, and each costs about 1,600 tokens.

| Command | Does |
|---|---|
| `/help` | Lists the commands |
| `/clear` | Starts a new session in the same workspace, after saying what the old one cost |
| `/undo` | Undoes the last turn: puts the files back and drops it from the conversation |
| `/rewind [turn]` | Lists the turns and the files each changed, or goes back to before one |
| `/compact` | Summarizes the older messages now, to free up context |
| `/model [name]` | Lists the models Zwans knows, or switches to one for the rest of the session (Tab completes the name; for any other model, use `zwans --resume <id> --model <name>`) |
| `/cost` | What the session has cost, and how full its context is |
| `/resume [n]` | Lists recent sessions in this workspace, or switches to one |
| `/exit` | Quits |

Everything is kept in `~/.zwans/`: sessions in `sessions.db`, an event log per session in
`transcripts/`, and the full text of tool output too long for the conversation in
`tool-output/`, where the model can `Read` and `Grep` it. A command's output over 2 MB is
already cut in the middle as it runs, and the model is told so.

`Grep` and `Glob` skip what `.gitignore` leaves out, and also `node_modules`, `.venv` and
the other folders checkpoints leave out, unless the path searched is inside one of them or
the glob names one.

### Permissions

Before each tool call, Zwans decides whether it runs, asks you first, or is refused. A
refused call goes back to the model as an error that says why.

| Mode (`--mode`) | Runs without asking | Asks |
|---|---|---|
| `read-only` | Reading, and commands that only read (`ls`, `git status`, `grep`) | Nothing: everything else is refused |
| `ask` (default) | The same | File changes and every other command |
| `auto` | Also edits, and commands that change files or run code (`pytest`, `make`, `git commit`) | Commands that use the network (`curl`, `pip install`, `git push`) or that Zwans can't classify |

The question shows what the call would do: an Edit's change as a diff of the file, a Write's
diff with a line saying whether it makes a new file or replaces one (and how many lines it
removes and adds), or the whole of a long command, here-document included. Escape codes in them are
shown as text (such as `\x1b`), so they can't hide part of the change. At a prompt, `y`
allows the call once, `a` allows that exact call, as shown, for the rest of the session, and
anything else (or Ctrl+C) declines. `a` isn't offered when it couldn't take effect: for a call
an `ask` rule covers, or a network command once untrusted content has been read. Text typed
while the turn was running is dropped first, so it can't answer by accident. When no one is at
a terminal, as with `zwans run` in a script, a call that needs asking is refused.

Bash commands are split into the simple commands they run before they're judged, so
`ls && rm -rf build` is a read and a delete, and `echo $(curl x)` contains a network call.
Commands that touch paths outside the workspace (other than `/tmp`), that come from a
variable, that print every environment variable (`env`, `printenv`), that move to a folder
the command doesn't name (`cd` alone, `cd -`), that run a program or script Zwans can't see
(`sed -f`, `awk -f`, `rg --pre`), or that Zwans can't parse count as unknown.

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

A Bash rule's pattern matches each simple command, with `*` matching anything. It sees the
command's redirections to files, so `Bash(cat)` doesn't allow `cat > app.py`, but not git's
global options, so `Bash(git push *)` covers `git -C . push`. An allow rule with a `*` (or a
bare `Bash`) doesn't cover a command that reaches outside the workspace; allow that exact
command instead.

File rules take gitignore-style globs, and an `Edit` rule also covers `Write`. They apply to
the files Bash commands name too: `Read` rules to what `cat`, `grep` or `< file` read, and
`Edit` rules to what `cp`, `mv`, `rm`, `sed -i` or `> file` write, including a folder that
holds a covered file (`rm -rf .git`). Paths after a `cd` count from its folder, and on macOS
and Windows, whose file systems ignore case, so do path rules (`.GIT/config` is `.git/config`).
Not covered: a program that opens files from its own code (`python x.py`), a search through
a whole folder (`grep -r KEY .`), the files an archive or patch holds (`tar xf`, `unzip`,
`patch`, `git apply`), and git commands that don't name the files they change (`git reset`,
`git switch`). Deny wins over ask, and ask over allow. A rule that names a tool Zwans doesn't
have, such as `bash(...)`, is an error.

Changes to `.zwans/` and `.git/` always ask, from the file tools and from commands. A
project's policy file arrives with its code, so its deny and ask rules apply at once, but the
parts that loosen the policy (allow rules, `mode = "auto"`, hooks) apply only after you trust
that exact file at the prompt. Trusting it also covers the workspace scripts its hooks run, so
a change to the file or to one of those scripts needs trusting again.

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

A skill is a folder with a `SKILL.md`, in `~/.zwans/skills/`, a project's `.zwans/skills/`,
or a project's `.claude/skills/`, so skills written for Claude Code work as they are:

```markdown
---
name: release-notes
description: Write release notes from the git log. Use when asked for a changelog.
---
(the instructions, as long as they need to be)
```

Only the names and descriptions go in the system prompt. The model loads a skill's
instructions with the `Skill` tool when a task matches, and any other file in its folder the
same way. A project's skill replaces the user's skill of the same name, and one in
`.zwans/skills/` replaces one in `.claude/skills/`.

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

### Instruction files

Standing instructions go in `~/.zwans/ZWANS.md` for all projects, and for one project in
its folder's `ZWANS.md`, `CLAUDE.md` or `AGENTS.md`, so a repository set up for Claude Code
or another agent works as it is. They're added to the system prompt when a session starts:
the user's first, then the project's in the order `AGENTS.md`, `CLAUDE.md`, `ZWANS.md`, since
the later one wins where two disagree. A file that's a link to another, or says the same
thing, is read once.

A line that is only `@path/to/file.md` brings in that file, as in Claude Code: a `CLAUDE.md`
that says `@AGENTS.md` is `AGENTS.md`. Only files inside the project are brought in.

### Web search and fetch

The model can search the web (`web_search`) and read a page (`web_fetch`), for a library's
documentation or an error message. The Claude API runs both on Anthropic's servers, so:

- they work with every executor, and the jail or Docker doesn't keep them off the network;
- the policy can't stop a single search or fetch, though what they bring in counts as
  untrusted, so later changes are checked as after untrusted content;
- a search costs $0.01 on top of tokens, which the cost shown includes; a fetch costs only
  the tokens of the page, at most 25,000.

Each search and fetch shows as it happens, like a tool call, between the text written before
and after it. When an answer cites pages it found, Zwans lists them under it as Sources.

Set `web = false` to turn them off.

### To-do list

For a task with several steps, the model keeps a checklist with the `TodoWrite` tool and
updates it as it goes. The terminal prints it each time it changes; the web UI pins it above
the message box while the turn runs. Set `todos = false` to turn it off.

### Background commands

For a command that keeps running, such as a dev server or a watcher, the model sets
`run_in_background` on `Bash`. It gets a job id (`bg1`, ...) back at once, reads what the job
has printed since it last looked with `BashOutput` (which can wait for it to finish), and
stops it with `KillBash`. Jobs run through the same executor and policy as other commands,
and keep the last megabyte of their output. A job is stopped with everything it started,
including what's still running after its shell has exited (`server & echo started`), by
`KillBash` or when the session closes: on Ctrl+D, `exit`, the end of `zwans run`, SIGTERM,
or the terminal closing (SIGHUP; Zwans then exits with 128 plus the signal's number). A
command run without `run_in_background` has whatever it left running stopped when it exits.

### Checkpoints

Before each turn, Zwans snapshots the workspace into a git repository of its own in
`~/.zwans/checkpoints/`, so `/undo` and `/rewind` can put the files back. It never touches
the project's `.git`, and it works in folders that aren't git repositories. After an undo,
the prompt of the undone turn is back in the input line, to edit and send again.

A snapshot holds what git would, so files the project's `.gitignore` leaves out, and folders
like `node_modules`, aren't brought back. Nor is anything a command did outside the
workspace, such as installing a package. If snapshotting takes over a minute, or fails (as
when the workspace is moved or deleted mid-session), checkpoints turn off for the session and
Zwans says why. Set `checkpoints = false` to turn them off yourself.

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
  Always allow (only when it would take effect, as in the terminal) and Deny, and an Edit or
  Write shows the diff it would make. A Task call lists what its subagent did.
- **One session, many clients:** every browser tab and `zwans attach` on the same session
  sees the whole conversation and every new event, and any of them can send the next task
  or answer a question. `zwans attach` asks the same way the chat does, with the same preview. Ctrl+C in `zwans attach` interrupts the turn; with nothing running,
  it detaches and the session keeps going in the server.
- **Evals:** every run in `evals/reports/` with a pass-rate chart per suite, each run's
  attempts and transcripts, and `compare` with its confidence intervals. Pick a task to see
  two attempts' transcripts side by side, lined up step by step, with the first step where
  they differ marked: that's where a regression starts.

While working on the UI, `zwans serve --dev-origin http://localhost:3000` lets `npm run dev`
(with `NEXT_PUBLIC_ZWANS_API=http://localhost:8765`) call the API.

## Desktop app

`desktop/` puts Zwans in its own window (macOS, Electron). It runs the Zwans installed from
this checkout, from this folder, so it uses the same `.env` and `~/.zwans/config.toml`.

```bash
cd desktop && npm install
npm run app    # build the web UI and open the app
npm run pack   # or build desktop/dist/Zwans-darwin-arm64/Zwans.app
```

`Zwans.app` can go in Applications or the Dock, but it keeps pointing at this checkout: after
changing the web UI, `npm --prefix web run build` is enough; after moving the repo or changing
`desktop/`, run `npm run pack` again. Closing the window stops its sessions, which you can
resume from the sidebar. Commands run directly on the Mac (the jail is Linux-only), so
stay in `ask` mode unless you trust the task.

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
| `todos` | `true` | Offer the `TodoWrite` tool |
| `checkpoints` | `true` | Snapshot the workspace before each turn, so `/undo` can put files back |
| `web` | `true` | Offer web search and fetch, which the Claude API runs |
| `subagent_max_steps` | `30` | Model calls allowed in one subagent's task |
| `compact_at` | `200000` | Estimated context tokens that trigger a compaction |
| `keep_messages` | `8` | Recent messages kept word for word when compacting |
| `prompt_cache` | `conversation` | What prompt caching covers: `conversation` (system prompt, tools and the conversation so far), `system` (system prompt and tools), or `off` |
| `shell` | found automatically | Path to bash |
| `executor` | `local` | Where commands run: `local`, `docker`, or `jail` (Linux) |
| `home` | `~/.zwans` | Where transcripts, saved sessions, saved tool output, and the policy file go |
| `mcp_servers` | none | MCP servers, by name; see above |

A setting that isn't valid, or a file `ZWANS_CONFIG` names that doesn't exist, stops Zwans
with a message naming the file or variable to fix.

## Development

```bash
ruff check . && ruff format --check . && mypy && pytest
ZWANS_LIVE_TESTS=1 pytest -s tests/test_example.py   # also run against the real API
cd web && npm run lint && npm run typecheck && npm test && npm run build
```
