/** A unified diff of several files, cut into one piece per file. */

export interface FileDiff {
  /** The file's path, from its +++ line (or its --- line, for a file that was deleted). */
  path: string;
  text: string;
}

const named = (line: string) => line.replace(/^(---|\+\+\+) /, "").replace(/^[ab]\//, "").trim();

/**
 * MultiEdit and Rename report one diff covering every file they changed, each file's part
 * starting with its own `--- a/path` and `+++ b/path` lines (or git's `diff --git`). The
 * diff viewer shows one file at a time, and given them all at once it runs their hunks
 * together, so they are cut apart here.
 */
export function splitDiff(text: string): FileDiff[] {
  const lines = text.split("\n");
  const git = lines.some((line) => line.startsWith("diff --git "));
  const starts: number[] = [];
  lines.forEach((line, i) => {
    const begins = git
      ? line.startsWith("diff --git ")
      : line.startsWith("--- ") && (lines[i + 1] ?? "").startsWith("+++ ");
    if (begins) starts.push(i);
  });
  if (starts.length === 0) return [{ path: "", text }];
  return starts.map((start, n) => {
    const part = lines.slice(start, starts[n + 1] ?? lines.length);
    const minus = part.find((line) => line.startsWith("--- ")) ?? "";
    const plus = part.find((line) => line.startsWith("+++ ")) ?? "";
    const path = named(plus) === "/dev/null" || !plus ? named(minus) : named(plus);
    // Every part but the last was cut just before a line break, which it gets back.
    return { path, text: part.join("\n") + (n < starts.length - 1 ? "\n" : "") };
  });
}
