# Findings

Eval results that shaped Zwans. Each entry gives the setup, the numbers, and what it means.
Reports live in `evals/reports/` (not committed); the numbers here are copied from them.

## 2026-10-28: the starter suite is too easy to measure anything

**Setup.** The 27-task starter suite (10 bug fixes, 8 features, 4 refactors, 5 questions),
one attempt per task, Zwans 0.1.0 at commit `4167cde`, local execution.

| Model, effort | Passed | Spent | Mean $ / task | Model calls | Tool calls | Tool errors |
|---|---|---|---|---|---|---|
| claude-opus-5-5, medium | 27/27 | $2.00 | 0.074 | 4.7 | 4.5 | 0% |
| claude-sonnet-5-5, low | 27/27 | $0.61 | 0.023 | 3.9 | 4.1 | 0% |
| claude-sonnet-5-5, low, `vague-edit` config | 27/27 | $0.60 | 0.022 | 3.9 | 4.0 | 0% |

`zwans eval compare` between the last two rows found no significant difference in any
metric (pass rate +0 pts; dollars -0.0005, 95% interval [-0.0012, +0.0003]).

**What it means.**
- Both models pass everything, so pass rate can't separate configs: there is no room to drop.
  The Phase 3 check "a deliberately broken config shows a significant drop" fails, because
  of the suite, not the statistics.
- Replacing the Edit description with "Edit a file." changed nothing. The input fields keep
  their own descriptions (`old_string`: "The exact text to replace..."), and on 100-300 line
  repos the model rarely needs more. A config meant to be broken has to break more than that.
- A pass costs 2 to 16 cents with Opus, so `--repeats 3` on the whole suite is about $6.

**Next.**
- Harder tasks: larger repos (a few thousand lines), bugs whose cause is far from the
  symptom, features with an under-specified interface the agent must infer from the code,
  and long multi-step changes. Aim for a 50-80% pass rate on Sonnet at low effort.
- A broken config that really hurts, e.g. Edit descriptions and field descriptions removed,
  or a misleading description, to calibrate what `compare` can detect.
- Claude Code baseline: not recorded yet. Run
  `zwans eval run --agent claude-code --repeats 3` (it runs `claude -p` with permission
  prompts off in a throwaway copy of each task).
- Older models: the provider always asks for adaptive thinking, which Haiku 4.5 rejects
  ("adaptive thinking is not supported on this model"), so it can't be evaluated yet.

## 2026-10-28: a misleading tool description costs time, not passes

**Setup.** The 27-task starter suite on claude-sonnet-5-5 at low effort, one attempt per
task, with `misleading-edit.toml`: Edit's description says old_string is a line range like
"12-15", which the tool doesn't accept.

| Config | Passed | Mean $ | Tool calls | Time |
|---|---|---|---|---|
| default | 27/27 | 0.0227 | 4.1 | 9.5s |
| misleading-edit | 27/27 | 0.0245 | 4.8 | 11.9s |

`compare` marks cost (+8%, interval [+0.0006, +0.0034]), tool calls and time as
significantly worse. Only 3 of 32 Edit calls failed: the model mostly follows the input
field's own description ("The exact text to replace") over the tool description, and after
one failure it corrects itself.

**What it means.** `compare` does detect a real degradation even on a saturated suite, through
cost and tool calls. Tool descriptions matter less than expected while the input schema is
clear, so experiments on descriptions should change both.

## 2026-10-28: a hard tier, calibrated

**Setup.** 12 tasks in `evals/tasks-hard/` (4 bug hunts in 800-2200 line repos, 4 features
that must follow an existing codebase's conventions, 2 implementations against a 3-page
spec, a subtle algorithm bug, a question needing real tracing), on claude-sonnet-5-5 at low
effort, one attempt per task.

| Task | Result | Model calls | Cost |
|---|---|---|---|
| `cadence-rules` | passed | 5 | $0.189 |
| `feed-cursor-skips` | passed | 6 | $0.066 |
| `fulfil-partial-shipments` | passed | 6 | $0.099 |
| `invoice-approvers-prod` | passed | 5 | $0.034 |
| `library-import-missing-loans` | failed | 15 | $0.138 |
| `markbook-tags-migration` | passed | 11 | $0.235 |
| `meetslot-freebusy` | failed | 6 | $0.086 |
| `orderdesk-refund` | passed | 7 | $0.120 |
| `scheduler-dst-shift` | passed | 6 | $0.067 |
| `sitegen-stale-listings` | passed | 8 | $0.104 |
| `stockroom-tenants` | passed | 11 | $0.204 |
| `strata-config` | passed | 9 | $0.338 |

10/12 (83%) for $1.68, about 14 cents a task. Both failures are the trap each task was built
around: the agent fixed the branch lookup but not the shared `group_by` that drops the end
of the file, and fixed meetslot's two visible bugs but not the UTC-offset sign or night
shifts the docstrings describe.

**Pitfall: don't let the Mac sleep during a run.** `cadence-rules` and `strata-config` first
failed twice with "The connection to the Claude API kept dropping mid-reply". The Mac was
sleeping: their attempts measured 260 s of monotonic time over 73 minutes of real time, and
`pmset -g log` showed sleep and dark-wake cycles. They are the tasks with one long model call
(writing a whole implementation), which spans a sleep; tasks with many short calls slip
between wake-ups. Run long evals with `caffeinate -s -i` on power, lid open.

**Correction (same day, three attempts per task).** The 83% was noise: with `--repeats 3`
the default config passes 35/36 (97%), including 3/3 on both tasks that failed above. See
the next entry.

## 2026-10-28: the hard tier saturates too; only tool calls separate the configs

**Setup.** `evals/tasks-hard/`, claude-sonnet-5-5 at low effort, `--repeats 3`, default
config against `misleading-edit`. $4.29 and $4.50.

| Metric | default | misleading-edit | B - A | 95% interval |
|---|---|---|---|---|
| Pass rate | 97% (35/36) | 97% (35/36) | +0 pts | [-8, +8] |
| Mean $ / attempt | 0.119 | 0.125 | +0.006 | [-0.005, +0.019] |
| Model calls | 6.8 | 7.0 | +0.2 | [-0.7, +1.1] |
| Tool calls | 7.9 | 10.6 | +2.7 | [+0.5, +5.3], significant |
| Tool errors | 0.1 | 0.9 | +0.8 | [-0.0, +2.3] |

Each config lost one attempt, on different tasks (`orderdesk-refund` and
`fulfil-partial-shipments`). The misleading description hit hardest on `feed-cursor-skips`,
where 38% of tool calls failed (23 calls per attempt against 8), but the model still got
there.

**What it means.**
- A single attempt per task is not a calibration. The one-attempt run looked like 83% and
  was really about 97%. Use `--repeats 3` before judging a task's difficulty.
- Sonnet 5.5, even at low effort, recovers from a wrong tool description at the cost of a
  few extra tool calls. With pass rates near 100%, `compare` can only see such changes in
  tool calls and cost, and needs repeats to do it.
- Making tasks harder by hand has hit diminishing returns: tasks built around specific traps
  were passed 3/3 on rerun. To get room below the ceiling, a weaker setup is cheaper than
  ever-harder tasks: support models without adaptive thinking (Haiku 4.5, see above), or cap
  `max_steps` or `max_cost` per attempt so that inefficiency turns into failures.

## 2026-10-28: Haiku 5.5 saturates too; Haiku 4.5 leaves room

**Setup.** Both tiers, `--repeats 3`, effort low (Haiku 4.5 has no effort levels; low maps
to a 2,048-token thinking budget), default config, `max_steps` 50.

| Model | Tier | Passed | Spent | Mean $ / attempt | Model calls |
|---|---|---|---|---|---|
| claude-haiku-5-5 | starter | 81/81 (100%) | $0.17 | 0.002 | 4.8 |
| claude-haiku-5-5 | hard | 34/36 (94%) | $0.55 | 0.015 | 11.4 |
| claude-haiku-4-5 | hard | 4/17 (24%) | $5.04 | 0.258 | 41.1 |

The Haiku 4.5 run hit its $5 budget after 17 of 36 attempts. Six attempts ran into the
50-call limit; it passed only `feed-cursor-skips` and `invoice-approvers-prod` (2/2 each).

**What it means.**
- Haiku 5.5 does the hard tier nearly as well as Sonnet 5.5 at a fortieth of the cost
  (1.5 cents an attempt). It is the cheapest way to run repeated experiments, but its pass
  rate is at the ceiling too, so experiments on it are read through cost and tool calls.
- Haiku 4.5 is the first setup with room below the ceiling: 24% on the hard tier. It is
  also 17x more expensive per attempt than Haiku 5.5, because it flounders: 41 model calls
  per attempt against 11. A full hard-tier run at three repeats would cost about $9.
- Experiments that need pass rate to move should run on Haiku 4.5 (or on a larger, harder
  suite). Experiments on efficiency (tool descriptions, prompts, caching, compaction) can
  run on Haiku 5.5 for well under a dollar.

Running out of `max_steps` used to be reported as an error, which `eval run` then flagged as
"may not be the agent's" failure. It now ends the turn with stop reason `max_steps`.
