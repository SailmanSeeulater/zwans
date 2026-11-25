"""linediff: line diffs, unified hunks and patches."""

from linediff.diff import diff
from linediff.ops import DELETE, INSERT, KEEP, Op, edit_count
from linediff.patch import Hunk, PatchError, apply, parse
from linediff.unified import unified

__all__ = [
    "DELETE",
    "INSERT",
    "KEEP",
    "Hunk",
    "Op",
    "PatchError",
    "apply",
    "diff",
    "edit_count",
    "parse",
    "unified",
]
