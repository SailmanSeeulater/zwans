---
name: debug
description: For any failing test, error, crash or wrong output to find the cause of and fix. Step by step - reproduce it, trace the bad value back to where it went wrong, prove the cause, fix it there (not the symptom) and check.
---
# Debugging: from the symptom back to the cause

Work like a detective: every claim about why it fails needs evidence you saw in this session,
not a guess that sounds right. Don't change code until you can say what the cause is and
how you know.

Keep the case on a todo list (TodoWrite) as you go: the symptom, what you've ruled out, and
the chain from the symptom to the cause as it grows.

## 1. Pin down the failure

Write down, in one or two lines:

- the exact command or action that fails;
- what happens: the error message and where it's raised, or the wrong output;
- what should happen instead.

If you were handed only a description ("the export is broken"), turn it into a command that
shows it before going further.

## 2. Reproduce it

Run the failing command yourself and see the failure with your own eyes. Then make it
smaller: one test instead of the suite, one input instead of the file, a few lines in a
script instead of the app. A quick repro is what every later step leans on.

- If it fails in CI but you haven't seen it here, use the CI tool to read the failed run.
- If you can't make it fail, that is a finding: compare what differs (versions, environment
  variables, data, the order tests run in, time, the network) instead of guessing at code.

## 3. Read all the evidence

- Read the whole traceback. The first error is usually the cause; later ones often follow
  from it. Note the deepest frame that is in this project's own code.
- For a long log, use Logs to see the kinds of line and where they change, rather than
  reading the tail and guessing.
- Diagnostics (linters, type checkers) can point straight at a wrong type or an undefined
  name.
- Read the code that ran, not what its name or comments promise. Open the function at the
  line in the traceback and the functions it calls.

## 4. Trace backwards

Start at the line where things visibly go wrong and ask of the bad value or state: where did
this come from? Follow it one step back at a time, through the caller, the argument, the
config, the file it was read from, until you reach the place where a correct value turned
into a wrong one. That place is the cause; everything after it is symptoms.

At each step, check rather than assume: print the value, add a temporary assert, or run a
few lines in a script or the Python tool. Grep for every place that sets or changes the
value. Write the chain down as you go, for example:

> `total` is None at report.py:88, because `summarize()` returned None at stats.py:40,
> because its early return on an empty list has no value, and the list is empty because
> `load()` skips rows with a header it doesn't recognize.

## 5. Test one idea at a time

When the trail forks, list two or three explanations, and for each one what you would see if
it were true. Run the check that tells them apart. Change one thing per experiment, so a
change in the result has one explanation. Undo temporary prints and experiments once they've
answered their question.

## 6. If it used to work

- History on the failing lines shows who changed them, when, and in which commit's words.
- Bisect finds the commit that broke it, given a commit where it worked and the repro as a
  command that exits non-zero when it's broken.

The commit that broke it usually says what was meant, which tells you what the fix should
keep.

## 7. Prove the cause

Before fixing, show that the cause you named is the cause: a test, or the smallest repro,
that fails for exactly that reason. Where you can, make it fail and pass on purpose by
changing only that one thing. If the proof doesn't hold, go back to step 4 with what you
learned.

## 8. Fix the cause, not the symptom

Change the place where the value went wrong. Not acceptable as fixes: catching and ignoring
the error, a special case for the input that failed, weakening or skipping the test, or
retrying until it passes. If the real fix is out of reach (another team's code, a design
question), say so and stop rather than papering over it.

## 9. Check

Run the original repro, the test from step 7, and the tests around the code you changed,
once each. Everything that passed before should still pass. Once they do, go straight to
the report: running the same checks again tells you nothing new.

## 10. Report

Say, briefly:

- the chain from the symptom to the cause, with the files and lines;
- what you changed and why that's the right place;
- how you checked it, and anything you couldn't check.

Then you're done: end your turn with the report, without another tool call.

## When you're stuck

- After two or three fixes that didn't work, stop changing code. One of your assumptions is
  wrong: list them and check each one, starting with the one you're surest of.
- "It should work" is a hypothesis. Find out what it actually does.
- Question the setup too: the right file, the right branch, the code that's installed rather
  than the copy you're editing, a stale build or cache.
- If the cause is outside the code (data, environment, a service that's down), the fix may
  not be a code change. Say what you found and ask.
