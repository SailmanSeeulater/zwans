# Zwans

A coding agent built from scratch: the loop that calls the model, the tools it uses, and
(in later phases) the sandbox and the evals that prove it works. See [SPEC.md](SPEC.md) for
the full plan.

**Status:** Phases 0 and 1 are done. Zwans can read, search, and edit a project and run its
tests. There are no permission prompts or sandbox yet (Phase 4), so point it at a folder you
don't mind it changing.

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
python examples/run_demo.py --scripted       # demo with a scripted model: free, offline
python examples/run_demo.py                  # the same demo with the real model
```

Ctrl+C stops the running turn and keeps the conversation. Each session's events are saved
to `~/.zwans/transcripts/`, and the session's cost is printed at exit.

## Configuration

`~/.zwans/config.toml`, or the same names as `ZWANS_*` environment variables:

| Setting | Default | Meaning |
|---|---|---|
| `model` | `claude-opus-5-5` | Model to call |
| `auth` | `api_key` | `api_key` or `subscription` |
| `effort` | `medium` | How much the model thinks: `low` to `max` |
| `max_tokens` | `64000` | Output limit per model call, thinking included |
| `max_steps` | `50` | Model calls allowed in one turn |
| `shell` | found automatically | Path to bash |
| `transcript_dir` | `~/.zwans/transcripts` | Where transcripts go |

## Development

```bash
ruff check . && ruff format --check . && mypy && pytest
ZWANS_LIVE_TESTS=1 pytest tests/test_example.py   # also run against the real API
```
