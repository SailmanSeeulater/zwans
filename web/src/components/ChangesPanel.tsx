"use client";

import { ChevronRight, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";
import type { SessionChanges, UndoableTurns } from "@/lib/api";
import { splitDiff } from "@/lib/diff";
import { DiffBody } from "./DiffBody";
import { DiffCount } from "./Glance";

interface Props {
  data: SessionChanges | null;
  undoable: UndoableTurns | null;
  /** Unset while a turn runs: nothing can be undone then. */
  onUndo?: (turn: number) => void;
}

const MARK = { added: "A", changed: "M", deleted: "D" } as const;

/**
 * The side pane's Changes tab: every file the session has changed so far, from its first
 * checkpoint to now, each opening to its diff, and the turns it can be put back to. It comes
 * from the checkpoints, so what Bash changed is here as well as what the edit tools did.
 */
export function ChangesPanel({ data, undoable, onUndo }: Props) {
  const diffs = useMemo(() => {
    const byPath = new Map<string, string>();
    for (const part of splitDiff(data?.diff ?? "")) if (part.path) byPath.set(part.path, part.text);
    return byPath;
  }, [data?.diff]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (path: string) =>
    setOpen((was) => {
      const next = new Set(was);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  if (data === null) return <div className="inspector muted small">Looking for changes…</div>;
  if (data.problem) {
    return (
      <div className="inspector">
        <h2>Changes</h2>
        <p className="muted small">{data.problem}</p>
      </div>
    );
  }

  const files = data.changes;
  const allOpen = files.length > 0 && files.every((f) => open.has(f.path));

  return (
    <div className="inspector changes">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>Changes</h2>
        {files.length > 0 && <DiffCount diff={data.diff} />}
      </div>
      {files.length === 0 ? (
        <div className="changes-empty">
          <p>Nothing changed yet.</p>
          <p className="muted small">Files the session writes, edits or deletes show here, with their diffs.</p>
        </div>
      ) : (
        <>
          <div className="row changes-head">
            <span className="muted small">
              {files.length} file{files.length === 1 ? "" : "s"} since the session started
            </span>
            <button
              className="button button-quiet button-small"
              onClick={() => setOpen(allOpen ? new Set() : new Set(files.map((f) => f.path)))}
            >
              {allOpen ? "Collapse all" : "Expand all"}
            </button>
          </div>
          <ul className="changes-files">
            {files.map((file) => {
              const diff = diffs.get(file.path) ?? "";
              const shown = open.has(file.path);
              const slash = file.path.lastIndexOf("/");
              return (
                <li key={file.path} className="changes-file" data-open={shown || undefined}>
                  <button className="changes-file-row" aria-expanded={shown} onClick={() => toggle(file.path)}>
                    <ChevronRight size={13} className="changes-chevron" aria-hidden="true" />
                    <span className="changes-mark" data-status={file.status} title={file.status}>
                      {MARK[file.status]}
                    </span>
                    <span className="changes-path mono" title={file.path}>
                      <span className="changes-path-in">
                        {slash >= 0 && <span className="changes-dir">{file.path.slice(0, slash + 1)}</span>}
                        {file.path.slice(slash + 1)}
                      </span>
                    </span>
                    {diff && <DiffCount diff={diff} />}
                  </button>
                  {shown && (
                    <div className="changes-diff">
                      {diff ? <DiffBody text={diff} /> : <p className="muted small">No text diff (a binary file).</p>}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
          {data.cut && (
            <p className="muted small">The diff was too long to send whole, so the last files may be cut short.</p>
          )}
        </>
      )}
      {undoable && undoable.turns.length > 0 && (
        <section className="changes-turns">
          <h3>Put back to before a turn</h3>
          <ul>
            {undoable.turns.map((turn) => (
              <li key={turn.turn} className="changes-turn">
                <span className="changes-turn-n mono">{turn.turn}</span>
                <span className="changes-turn-prompt" title={turn.prompt}>
                  {turn.prompt || "(no prompt)"}
                  <span className="muted small">
                    {" "}
                    · {turn.changes.length} file
                    {turn.changes.length === 1 ? "" : "s"}
                  </span>
                </span>
                <button
                  className="button button-quiet button-small"
                  disabled={!onUndo}
                  onClick={() => onUndo?.(turn.turn)}
                  title={onUndo ? `Undo turn ${turn.turn} and everything after it` : "Wait for the turn to finish"}
                >
                  <RotateCcw size={12} aria-hidden="true" /> Undo
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
