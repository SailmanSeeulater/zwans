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
