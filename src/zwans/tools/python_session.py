"""The Python tool: a Python session that keeps its variables between calls.

Bash starts a new interpreter every time, so anything worked out is gone by the next call.
Here a value computed in one call is there in the next, as in a notebook, which is what
exploring data or checking a calculation needs.

One interpreter runs for the life of the Zwans session, started by the session's executor,
so it is sandboxed whenever commands are. A chat, which has no project, gets it only inside
a sandbox of its own, with an empty folder and no network; there it needs no permission,
because there is nothing for it to reach.
"""

import asyncio
import contextlib
import json
import shlex
from typing import Any

from pydantic import BaseModel, Field

from zwans.executor.local import LocalExecutor
from zwans.tools.base import ToolContext, ToolError, ToolOutput

MAX_OUTPUT_CHARS = 12_000  # of one call's output; also keeps a reply within one pipe read

# The interpreter's side. It reads one JSON line per call and answers with one. Answers go
# out on a copy of the original stdout; stdout and stderr themselves are closed off, so a
# program the code starts can't write into the answers.
DRIVER = f"""
import ast, contextlib, io, json, os, sys, traceback
answers = os.fdopen(os.dup(1), "w", encoding="utf-8")
nowhere = os.open(os.devnull, os.O_WRONLY)
os.dup2(nowhere, 1)
os.dup2(nowhere, 2)
space = {{"__name__": "__main__"}}
for line in sys.stdin:
    code = json.loads(line)["code"]
    out = io.StringIO()
    ok = True
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            tree = ast.parse(code, "<session>")
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            exec(compile(tree, "<session>", "exec"), space)
            if last is not None:
                value = eval(compile(ast.Expression(last.value), "<session>", "eval"), space)
                if value is not None:
                    print(repr(value))
    except BaseException:
        ok = False
        kind, error, trace = sys.exc_info()
        out.write("".join(traceback.format_exception(kind, error, trace.tb_next)))
    text = out.getvalue()
    if len(text) > {MAX_OUTPUT_CHARS}:
        text = text[:{MAX_OUTPUT_CHARS}] + "\\n[... output cut short]"
    answers.write(json.dumps({{"ok": ok, "output": text}}, ensure_ascii=False) + "\\n")
    answers.flush()
"""


class PythonInput(BaseModel):
    code: str = Field(
        min_length=1,
        description="Python to run. Variables, imports and functions from earlier calls are "
        "still there. The value of a last line that is an expression is shown, as in a "
        "notebook.",
    )
    timeout: int = Field(default=60, ge=1, le=600, description="Seconds to wait for it.")
    restart: bool = Field(
        default=False, description="Start a fresh interpreter first, dropping every variable."
    )


class PythonTool:
    name = "Python"
    description = (
        "Run Python in a session that keeps its state: what one call defines, the next can "
        "use. Use it to calculate, to explore data step by step, and to try out a snippet "
        "before writing it into a file. The value of the last expression is shown, along "
        "with anything printed. For running the project's tests or programs, use Bash."
    )
    input_model = PythonInput

    def __init__(self, sandbox: LocalExecutor | None = None) -> None:
        # A sandboxed executor of the tool's own, for a chat. Without one, the session's.
        self.sandbox = sandbox
        # In its own sandbox there's nothing to ask about, and no reason to wait in line.
        self.read_only = sandbox is not None
        self._process: asyncio.subprocess.Process | None = None
        self._owner: LocalExecutor | None = None
        self._lock = asyncio.Lock()  # one call at a time: they share the interpreter

    def commands(self, args: dict[str, Any]) -> list[str]:
        """What a call amounts to, for the policy to judge: `python -c` with the code, or
        nothing to judge inside the tool's own sandbox."""
        code = args.get("code")
        if self.sandbox is not None or not isinstance(code, str):
            return []
        return [f"python -c {shlex.quote(code)}"]

    async def run(self, args: PythonInput, ctx: ToolContext) -> ToolOutput:
        async with self._lock:
            if args.restart:
                await self.aclose()
            process = await self._started(ctx)
            assert process.stdin is not None and process.stdout is not None
            try:
                process.stdin.write((json.dumps({"code": args.code}) + "\n").encode("utf-8"))
                await process.stdin.drain()
                line = await asyncio.wait_for(process.stdout.readline(), args.timeout)
            except TimeoutError:
                await self.aclose()
                return ToolOutput(
                    content=f"Stopped after {args.timeout}s because it hadn't finished. The "
                    "session was restarted, so its variables are gone.",
                    is_error=True,
                )
            except (BrokenPipeError, ConnectionResetError):
                line = b""
            if not line:  # the interpreter is gone: it was killed, or the code ended it
                await self.aclose()
                return ToolOutput(
                    content="The Python session ended while running that, so its variables "
                    "are gone. The next call starts a fresh one.",
                    is_error=True,
                )
        reply = json.loads(line)
        output = str(reply.get("output", "")).rstrip()
        return ToolOutput(content=output or "(no output)", is_error=not reply.get("ok"))

    async def aclose(self) -> None:
        """Stop the interpreter. The session calls this when it closes."""
        process, owner = self._process, self._owner
        self._process = self._owner = None
        if process is not None and owner is not None:
            with contextlib.suppress(OSError):
                await owner.stop_process(process)

    async def _started(self, ctx: ToolContext) -> asyncio.subprocess.Process:
        if self._process is not None and self._process.returncode is None:
            return self._process
        executor = self.sandbox or ctx.executor
        if not isinstance(executor, LocalExecutor) or not executor.interactive:
            raise ToolError("The Python tool can't keep a session running in this executor.")
        for program in ("python", "python3"):
            try:
                self._process = await executor.start_process(
                    [program, "-u", "-c", DRIVER], stdin=True
                )
            except FileNotFoundError:
                continue
            self._owner = executor
            return self._process
        raise ToolError("Python isn't installed here, or isn't on PATH.")
