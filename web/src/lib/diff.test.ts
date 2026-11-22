import { describe, expect, it } from "vitest";
import { splitDiff } from "./diff";

const A = "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n-def total(v):\n+def sum_values(v):\n     return sum(v)\n";
const B = "--- a/pkg/report.py\n+++ b/pkg/report.py\n@@ -1 +1 @@\n-from calc import total\n+from calc import sum_values\n";

describe("splitDiff", () => {
  it("cuts a diff of several files into one piece per file", () => {
    const parts = splitDiff(A + B);

    expect(parts.map((p) => p.path)).toEqual(["calc.py", "pkg/report.py"]);
    expect(parts[0]?.text).toBe(A);
    expect(parts[1]?.text).toBe(B);
  });

  it("leaves a diff of one file whole", () => {
    expect(splitDiff(A)).toEqual([{ path: "calc.py", text: A }]);
  });

  it("isn't fooled by a removed line that starts with dashes", () => {
    // "--- old" as a removed line reads "---- old" in a diff; only a real header is
    // followed by a +++ line.
    const tricky = "--- a/notes.md\n+++ b/notes.md\n@@ -1,2 +1,2 @@\n---- old\n+-- new\n text\n";

    expect(splitDiff(tricky + B).map((p) => p.path)).toEqual(["notes.md", "pkg/report.py"]);
  });

  it("names a new file and a deleted one, and reads git's own diffs", () => {
    const added = "--- /dev/null\n+++ b/new.py\n@@ -0,0 +1 @@\n+x = 1\n";
    const git = "diff --git a/a.py b/a.py\nindex 1..2 100644\n--- a/a.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-x\n";

    expect(splitDiff(added)[0]?.path).toBe("new.py");
    expect(splitDiff(git + git).map((p) => p.path)).toEqual(["a.py", "a.py"]);
    expect(splitDiff("(The diff is too large to show.)")).toEqual([
      { path: "", text: "(The diff is too large to show.)" },
    ]);
  });
});
