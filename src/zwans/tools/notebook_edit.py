"""The NotebookEdit tool: change a Jupyter notebook a cell at a time.

A notebook is JSON, and editing it as text means matching a cell's source as a list of
quoted lines, escapes and all, beside outputs that can be pages of base64. Read shows a
notebook as numbered cells (tools/documents.py); this replaces, inserts or deletes one by
that number, or by its id. Changing a code cell clears its outputs, which no longer match.
"""

import json
import secrets
from typing import Any, Literal

from pydantic import BaseModel, Field

from zwans.tools.base import ToolContext, ToolError, ToolOutput
from zwans.tools.documents import load_notebook, text_of
from zwans.tools.text import unified_diff

Action = Literal["replace", "insert", "delete"]


class NotebookEditInput(BaseModel):
    path: str = Field(description="Path to the .ipynb file, relative to the workspace root.")
    cell: int | str = Field(
        description="The cell, by the number Read shows (from 0) or by its id. To insert, the "
        "number of the cell the new one goes before; the number of cells puts it at the end.",
    )
    action: Action = Field(default="replace", description="replace, insert or delete.")
    source: str = Field(default="", description="The cell's new source, for replace and insert.")
    cell_type: Literal["code", "markdown"] | None = Field(
        default=None,
        description="code or markdown. For insert it defaults to code; for replace, leave it "
        "out to keep the cell's type.",
    )


class NotebookEditTool:
    name = "NotebookEdit"
    description = (
        "Change one cell of a Jupyter notebook (.ipynb): replace its source, insert a new "
        "cell, or delete one. Name the cell by the number Read shows, or by its id. Read the "
        "notebook first. Replacing a code cell clears its outputs."
    )
    input_model = NotebookEditInput
    read_only = False

    async def preview(self, args: NotebookEditInput, ctx: ToolContext) -> str:
        """The change to the cell's source, for the user to see before allowing it."""
        _, _, diff = await self._edit(args, ctx)
        return diff

    async def run(self, args: NotebookEditInput, ctx: ToolContext) -> ToolOutput:
        notebook, said, diff = await self._edit(args, ctx)
        text = json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"
        await ctx.executor.write_bytes(args.path, text.encode("utf-8"))
        return ToolOutput(content=said, diff=diff)

    async def _edit(
        self, args: NotebookEditInput, ctx: ToolContext
    ) -> tuple[dict[str, Any], str, str]:
        """The notebook with the change made, what was done, and the diff of the cell."""
        if not args.path.endswith(".ipynb"):
            raise ToolError(f"{args.path} isn't a notebook: NotebookEdit changes .ipynb files.")
        notebook = load_notebook(await ctx.executor.read_bytes(args.path), args.path)
        cells: list[dict[str, Any]] = notebook["cells"]
        index = _index(cells, args.cell, inserting=args.action == "insert")
        label = f"{args.path} cell {index}"
        if args.action == "delete":
            old = cells.pop(index)
            before = text_of(old.get("source"))
            return (
                notebook,
                f"Deleted cell {index} of {args.path}.",
                unified_diff(label, before, ""),
            )
        if args.action == "insert":
            cell = _new_cell(args.cell_type or "code", args.source, notebook)
            cells.insert(index, cell)
            diff = unified_diff(label, "", args.source, new_file=True)
            return notebook, f"Inserted a {cell['cell_type']} cell at {index} in {args.path}.", diff
        cell = cells[index]
        before = text_of(cell.get("source"))
        was = cell.get("cell_type", "code")
        kind = args.cell_type or was
        if kind != was:
            cells[index] = cell = {**_new_cell(kind, "", notebook), "id": cell.get("id")}
            if cell["id"] is None:
                del cell["id"]
        cell["source"] = _lines(args.source)
        if kind == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        said = f"Replaced cell {index} of {args.path}"
        said += f", now a {kind} cell." if kind != was else "."
        return notebook, said, unified_diff(label, before, args.source)


def _index(cells: list[dict[str, Any]], cell: int | str, inserting: bool) -> int:
    if isinstance(cell, str) and not cell.strip().lstrip("-").isdigit():
        for index, each in enumerate(cells):
            if each.get("id") == cell:
                return index
        raise ToolError(f"There is no cell with the id {cell!r}.")
    index = int(cell)
    top = len(cells) if inserting else len(cells) - 1
    if not 0 <= index <= top:
        raise ToolError(f"There is no cell {index}: the cells are numbered 0 to {len(cells) - 1}.")
    return index


def _lines(source: str) -> list[str]:
    """Source as notebooks keep it: lines with their newlines, the last without one."""
    return source.splitlines(keepends=True)


def _new_cell(kind: str, source: str, notebook: dict[str, Any]) -> dict[str, Any]:
    cell: dict[str, Any] = {"cell_type": kind, "metadata": {}, "source": _lines(source)}
    # Cells have ids from format 4.5 on.
    if (notebook.get("nbformat"), notebook.get("nbformat_minor", 0)) >= (4, 5):
        cell = {"id": secrets.token_hex(4), **cell}
    if kind == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    return cell
