# Zwans

A coding agent built from scratch: the loop that calls the model, the tools it uses, and
(in later phases) the sandbox and the evals that prove it works. See [SPEC.md](SPEC.md) for
the full plan.

**Status:** Phases 0 to 2 are done, and Phase 3 (evals) is under way with a starter suite
of 27 tasks. Zwans can read, search, and edit a project and run its tests; it saves and
resumes sessions, compacts long ones, and caches prompts. There are no permission prompts or
sandbox yet (Phase 4), so point it at a folder you don't mind it changing.

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

### ZWANS.md

Standing instructions go in `ZWANS.md`: `~/.zwans/ZWANS.md` for all projects, and one in a
project's folder for that project. Both are added to the system prompt when a session
starts, the project's last.

### Long sessions

When the conversation passes `compact_at` tokens, Zwans has the model write handoff notes
for the older part and keeps the latest `keep_messages` messages word for word.

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

`--agent claude-code` runs the same tasks through `claude -p` instead, with the same model,
effort, limits and checks, to see how far Zwans is from a production harness. It runs with
`--bare`, so your own CLAUDE.md, hooks, plugins and MCP servers stay out of it; `--bare` only
accepts `ANTHROPIC_API_KEY`, so the baseline is billed per token whatever `auth` says. Its
cost is charged to `--budget` when each attempt ends, so a run can go over by up to one
task's `max_cost` per parallel attempt.

## Configuration

`~/.zwans/config.toml`, or the same names as `ZWANS_*` environment variables:

| Setting | Default | Meaning |
|---|---|---|
| `model` | `claude-opus-5-5` | Model to call |
| `auth` | `api_key` | `api_key` or `subscription` |
| `effort` | `medium` | How much the model thinks: `low` to `max` |
| `max_tokens` | `64000` | Output limit per model call, thinking included |
| `max_steps` | `50` | Model calls allowed in one turn |
| `compact_at` | `200000` | Estimated context tokens that trigger a compaction |
| `keep_messages` | `8` | Recent messages kept word for word when compacting |
| `shell` | found automatically | Path to bash |
| `home` | `~/.zwans` | Where transcripts, saved sessions, and saved tool output go |

## Development

```bash
ruff check . && ruff format --check . && mypy && pytest
ZWANS_LIVE_TESTS=1 pytest -s tests/test_example.py   # also run against the real API
```
