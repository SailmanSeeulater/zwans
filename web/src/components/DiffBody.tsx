"use client";

/**
 * One file's unified diff in react-diff-view, as an Edit or Write reports it. Colors come
 * from globals.css (.diff-table); the library's own stylesheet isn't used.
 */
import { useMemo } from "react";
import { Decoration, Diff, Hunk, markEdits, parseDiff, tokenize, type FileData, type HunkTokens } from "react-diff-view";

/** Word-level edit marks cost a diff per changed block; skip them on very long files. */
const MARK_EDITS_MAX_LINES = 800;

function parseOne(text: string): FileData | null {
  try {
    // The parser expects git's header; difflib's ---/+++ lines need one in front.
    return parseDiff(text.startsWith("diff --git") ? text : `diff --git a b\n${text}`)[0] ?? null;
  } catch {
    return null;
  }
}

function editTokens(file: FileData): HunkTokens | null {
  const lines = file.hunks.reduce((n, h) => n + h.changes.length, 0);
  if (lines > MARK_EDITS_MAX_LINES) return null;
  try {
    return tokenize(file.hunks, { enhancers: [markEdits(file.hunks, { type: "block" })] });
  } catch {
    return null;
  }
}

export function DiffBody({ text }: { text: string }) {
  const file = useMemo(() => parseOne(text), [text]);
  const tokens = useMemo(() => (file ? editTokens(file) : null), [file]);

  // A diff the parser can't read (or one too large to show) still shows, as text.
  if (!file || file.hunks.length === 0) return <pre className="raw">{text}</pre>;

  return (
    <Diff viewType="unified" diffType={file.type} hunks={file.hunks} tokens={tokens} className="diff-table" gutterType="default">
      {(hunks) =>
        hunks.flatMap((hunk, i) => [
          <Decoration key={`head-${i}`} className="diff-hunk-head">
            {hunk.content}
          </Decoration>,
          <Hunk key={`hunk-${i}`} hunk={hunk} />,
        ])
      }
    </Diff>
  );
}
