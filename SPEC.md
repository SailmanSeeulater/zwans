# Zwans: Build Spec

Zwans is an agent harness built from scratch: the loop, the tools, the sandbox, and the
evals that prove it works. NexTix orchestrates agents that already exist. Zwans *is* the agent.

**Goal:** a coding agent you own end to end, where every design choice is backed by an eval
result, not a guess.

**Non-goals:** competing with Claude Code on polish, supporting every model provider on day
one, Windows-native sandboxing.

---

## Architecture

```
            ┌──────────── CLI (zwans) ─────────────┐
            │                                       │
 Web UI ── Server (FastAPI, WebSocket) ── Eval runner
            │                                       │
            └──────────────┬────────────────────────┘
                           ▼
                    Agent core (loop)
        ┌──────────┬───────┴───────┬──────────────┐
     Provider    Tools         Context         Policy
   (Anthropic,  registry      manager         engine
    fake)          │                              │
                   ▼                              ▼
               Executor ◄──────────────── allow / ask / deny
          (local │ docker │ zwans-jail)
```

**Core principle: one event stream.** The core emits typed events. The CLI, web UI, eval
runner, and transcript writer are all just consumers of that stream. Nothing reaches into the
loop's internals.

```python
# zwans/events.py (sketch)
TurnStarted | TextDelta | ToolCallRequested | PermissionRequested | PermissionResolved
| ToolResult | ContextCompacted | UsageUpdated | TurnEnded | Error
```

**Tool interface**

```python
class Tool(Protocol):
    name: str
    description: str           # the model reads this; treat it as product copy
    input_model: type[BaseModel]
    read_only: bool            # read-only tools may run in parallel and skip "ask"
    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

`ToolContext` carries the executor, the policy decision, the cancellation token, and the
session's working directory. Tools never call `subprocess` or `open()` directly; they go
through the executor so the sandbox can be swapped underneath them.

## Repo layout

```
zwans/
  src/zwans/
    loop.py           agent loop
    events.py
    providers/        anthropic.py, fake.py (scripted, for tests)
    tools/            read, write, edit, glob, grep, bash, web_fetch, task (subagent)
    context/          tokens, truncation, compaction, instructions (ZWANS.md), cache
    session/          SQLite store, resume, rewind
    policy/           rules, modes, command classification, untrusted-content tagging
    executor/         local.py, docker.py, jail.py (Phase 7)
    mcp/              MCP client
    ext/              skills, hooks
    cli/              typer app
    server/           FastAPI + WebSocket
  evals/
    tasks/            one folder per task
    configs/          a.toml, b.toml ...
    reports/
  web/                Next.js
  sandbox-image/      Dockerfile for the default execution image
  runtime/            Rust zwans-jail (Phase 7)
  docs/
```

## Stack

| Piece | Choice |
|---|---|
| Core, CLI, evals, server | Python 3.12, asyncio, Pydantic, Typer, FastAPI |
| Model access | `anthropic` SDK, raw Messages API with streaming. **Not** the Agent SDK: owning the loop is the point |
| Storage | SQLite (sessions, eval results). Local-first, no services to run |
| Sandbox | Docker (Phases 4 to 6), then Rust `zwans-jail` on WSL2 (Phase 7) |
| Web | Next.js, the same toolchain as NexTix |
| Quality gates | ruff, mypy --strict, pytest, GitHub Actions CI |

---

## Phases

Each phase ends with a commit, a push, green CI, and its "Done when" checklist verified.

### Phase 0: Foundations
- Repo, `pyproject.toml`, 3.12 venv, ruff, mypy, pytest, CI.
- Event types and the `Tool` protocol.
- **Fake provider:** replays a scripted list of model responses (text and tool calls). Every
  loop test after this uses it, so tests are deterministic and cost nothing.
- `zwans --version`, config loading (`~/.zwans/config.toml`, `ZWANS_*` env vars).

**Done when**
- [ ] CI green on an empty-but-typed skeleton.
- [ ] A fake-provider test drives one full turn: text → tool call → tool result → final text.

### Phase 1: The loop and core tools
- Streaming Messages API client: retries with backoff, `stop_reason` handling, usage and cost
  tracking per turn.
- Loop: parallel execution of read-only tool calls, sequential for writes, max-turn limit,
  Ctrl+C cancels the running tool without killing the session.
- Tools: `Read` (line ranges, line numbers), `Write`, `Edit` (exact string match, fails on
  zero or multiple matches, `replace_all` flag), `Glob`, `Grep` (ripgrep), `Bash` (timeout,
  output cap).
- Local executor confined to the session's working directory.
- CLI: `zwans` (REPL) and `zwans run "<prompt>"` (one-shot, exits with a status code).
- JSONL transcript per session.

**Done when**
- [ ] On a seeded repo with a failing test, `zwans run "make the tests pass"` fixes it.
- [ ] Edit tool has tests for: no match, multiple matches, CRLF files, non-UTF-8 files.
- [ ] Ctrl+C during a long `Bash` call returns control with the session intact.
- [ ] Cost of each session is printed at exit.

### Phase 2: Sessions and context
- SQLite session store: `zwans --resume <id>`, `zwans sessions`, rewind to turn N.
- Token accounting from API usage, with a running context-size estimate.
- Large tool output: truncate in context, spill the full output to a file the model can `Read`.
- Compaction: at a configurable threshold, summarize older turns and keep recent ones verbatim.
- Prompt caching: cache breakpoints on system prompt, tools, and the stable conversation prefix.
- Instruction loading: `ZWANS.md` in the project and `~/.zwans/ZWANS.md`.

**Done when**
- [ ] A scripted 200-turn session survives at least two compactions and still finishes its task.
- [ ] Resume restores a session exactly, including pending tool state.
- [ ] Cache hit rate is reported per session and exceeds 70% on a long session.

### Phase 3: Eval platform
Built *before* the UI on purpose: from here on, every change is measured.

- **Task format:** a folder with `task.toml` (prompt, timeout, budget), a `repo/` snapshot or a
  git URL plus commit, and a `check` command whose exit code decides pass/fail. Hidden tests the
  agent can't see are copied in only at check time.
- **Starter suite:** 25 to 30 small tasks across bug fixes, features, refactors, and
  "read-only" questions with a checkable answer. Write your own so they are uncontaminated.
- **Runner:** each attempt runs in a fresh Docker container, N in parallel, K repeats per task.
- **Metrics:** pass rate, cost, turns, tool calls, wall time, tool error rate.
- **Compare:** `zwans eval compare a b` with bootstrap confidence intervals, so noise isn't
  mistaken for improvement.
- **Budget guard:** the run stops when a configured dollar cap is reached.
- **Baseline:** run the same suite through Claude Code headless (`claude -p`) to see how far
  Zwans is from a production harness.

**Done when**
- [ ] `zwans eval run core --config a.toml --repeats 3` produces a JSON and HTML report.
- [ ] A deliberately broken config (a vague `Edit` description) shows a significant drop in
      `compare`, and a no-op change shows no significant difference.
- [ ] Claude Code baseline numbers are recorded in `docs/findings.md`.

### Phase 4: Permissions and sandbox
- **Policy file** (`.zwans/policy.toml`): allow/ask/deny rules by tool, path glob, and command
  pattern. Deny wins over allow.
- **Modes:** `read-only`, `ask` (default), `auto` (allowlist runs without prompting).
- **Command classification:** parse shell commands (pipelines, `&&`, subshells) before matching
  rules, so `ls && rm -rf x` isn't approved as `ls`.
- **Docker executor:** workspace bind-mounted, no host network, egress through an allowlist
  proxy (reuse what you learned from the NexTix Squid setup).
- **Untrusted content:** tool output from files, web pages, and MCP servers is tagged; a policy
  can require "ask" for writes or network calls made right after untrusted content was read.
- **Injection suite:** repos and pages that contain planted instructions ("run curl ... |
  sh", "ignore previous instructions").

**Done when**
- [ ] Every denied action is reported back to the model as a tool error it can reason about.
- [ ] The injection suite passes 100% in `ask` mode with no planted action executed.
- [ ] The eval suite under the Docker executor loses no more than 2 points of pass rate
      versus local execution.

### Phase 5: Extensibility
- **Subagents:** a `Task` tool spawning a child loop with its own context, tool subset, and
  budget; only its final report returns to the parent.
- **MCP client:** stdio and streamable HTTP transports; MCP tools go through the same policy
  engine.
- **Skills:** folders with a `SKILL.md`; only names and descriptions are in context until the
  model loads one.
- **Hooks:** scripts on `pre_tool`, `post_tool`, `stop`, receiving JSON on stdin; a non-zero
  `pre_tool` exit blocks the call with the hook's message.

**Done when**
- [ ] Zwans uses the NexTix MCP server (`nextix mcp`) to read and comment on a ticket.
- [ ] An eval experiment compares the suite with and without subagents, recorded in findings.
- [ ] A `pre_tool` hook can block `git push` and the model sees why.

### Phase 6: Server and web UI
- FastAPI server exposing sessions; events over WebSocket; approvals sent back the same way.
- Web UI: streaming chat, tool-call timeline, inline diffs for `Edit`/`Write`, approval
  prompts, session list with resume.
- Eval dashboard: runs, pass-rate history, `compare` view, and a side-by-side transcript diff
  of the same task under two configs.

**Done when**
- [ ] A full task is completed from the browser, including approving and denying actions.
- [ ] The CLI and UI can attach to the same running session.
- [ ] A regression between two eval runs can be traced to a specific transcript divergence in
      the UI.

### Phase 7: Own runtime and hardening
- **`zwans-jail` (Rust, Linux/WSL2):** user/PID/mount/net namespaces, cgroups v2 limits,
  seccomp-bpf allowlist, Landlock path rules, an executor that speaks a small JSON protocol.
- **Escape suite:** fork bombs, memory bombs, `/proc` tricks, ptrace, leaked FDs, egress
  attempts. All must fail.
- **Findings write-up:** `docs/findings.md` with at least three eval-backed experiments (tool
  descriptions, compaction strategy, subagents, caching), each with numbers and transcripts.

**Done when**
- [ ] The jail executor passes the escape suite and matches Docker on eval pass rate.
- [ ] Sandbox startup under 50 ms (versus measured Docker startup).
- [ ] `findings.md` is complete enough to publish.

---

## Decisions to confirm before Phase 0

1. **Model access.** Zwans calls the Messages API directly, so it needs an **Anthropic API
   key** (pay per use). The `claude setup-token` plan token NexTix uses is meant for Claude
   Code, not for third-party harnesses. Check the current terms before trying it.
   *Recommendation:* API key with a monthly spend limit set in the Console, plus the eval budget
   guard. The fake provider keeps Phases 0 to 2 nearly free.
2. **Core language.** Python (faster iteration, easier evals) or TypeScript (matches Claude
   Code's ecosystem). *Recommendation:* Python; Rust only for `zwans-jail`.
3. **Storage.** SQLite or Postgres. *Recommendation:* SQLite. Zwans is local-first; NexTix
   already covers the multi-service setup.
4. **Providers.** Anthropic only, behind an interface, or multiple from the start.
   *Recommendation:* Anthropic plus the fake provider. A second real provider later makes a
   good eval experiment.
5. **Windows.** Phases 0 to 6 work on Windows with Docker Desktop. Phase 7 needs WSL2 with
   cgroups v2 and unprivileged user namespaces; verify that before starting it.

## Risks

| Risk | Mitigation |
|---|---|
| Eval costs add up | Budget guard, small tasks, fake provider for logic tests, cached prefixes |
| Eval noise hides real changes | K repeats and confidence intervals before any conclusion |
| Scope creep toward Claude Code parity | Every feature needs an eval reason or a "Done when" item |
| Sandbox gives false confidence | Threat model in `docs/security.md`, escape suite in CI |
| Windows path and encoding issues (as in NexTix) | UTF-8 everywhere, CRLF tests for `Edit`, CI on Linux and Windows |
