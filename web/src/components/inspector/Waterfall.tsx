"use client";

import { useState } from "react";
import { askedFor, cacheHitRate, contextTotal, counted, startedAt, type ModelCall } from "@/lib/calls";
import { pct, seconds, tokens } from "@/lib/format";
import { Empty, type InspectorProps } from "./Inspector";

type Filter = "all" | "errors" | "slow";

/** Draft 10: a turn's model calls on one timeline, with what each sent and got back. */
export function Waterfall({ data }: InspectorProps) {
  const turns = [...new Set(data.calls.map((c) => c.turn))];
  const [picked, setPicked] = useState<number | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const turn = picked ?? turns.at(-1);
  const calls = data.calls.filter((c) => c.turn === turn);

  if (!calls.length) return <Empty>No model calls yet.</Empty>;

  const timed = calls.every((c) => Number.isFinite(c.endedAt));
  const t0 = timed ? Math.min(...calls.map(startedAt)) : 0;
  const t1 = timed ? Math.max(...calls.map((c) => c.endedAt)) : 0;
  const span = Math.max(t1 - t0, 1);
  const median = [...calls].sort((a, b) => a.seconds - b.seconds)[Math.floor(calls.length / 2)]!.seconds;
  const shown = calls.filter((c) =>
    filter === "errors" ? c.toolError : filter === "slow" ? c.seconds > median * 1.5 : true,
  );
  const read = calls.reduce((sum, c) => sum + counted(c), 0);

  return (
    <section className="panel glass">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <div>
          <h1 style={{ margin: 0 }}>
            Turn {turn} · {calls.length} model {calls.length === 1 ? "call" : "calls"}
          </h1>
          <p className="muted">
            {timed ? `${seconds(span / 1000)} from first call to last · ` : ""}
            {tokens(read)} input tokens · {pct(cacheHitRate(calls))} from the cache
          </p>
        </div>
        <div className="row">
          {turns.length > 1 && (
            <select className="select" value={turn} onChange={(e) => setPicked(Number(e.target.value))} aria-label="Turn">
              {turns.map((t) => (
                <option key={t} value={t}>
                  Turn {t}
                </option>
              ))}
            </select>
          )}
          <div className="segmented" role="group" aria-label="Show">
            {(["all", "errors", "slow"] as const).map((f) => (
              <button key={f} aria-current={filter === f ? "page" : undefined} onClick={() => setFilter(f)}>
                {f === "all" ? "All" : f === "errors" ? "Tool errors" : "Slow"}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="table-scroll">
        <table className="table waterfall">
          <thead>
            <tr>
              <th className="num">#</th>
              <th>Asked for</th>
              <th>Stop</th>
              <th className="num">Context</th>
              <th className="num">Cache read</th>
              <th className="num">Cache write</th>
              <th className="num">Out</th>
              <th className="wf-time">Time</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((c) => (
              <Row key={c.n} call={c} t0={t0} span={span} timed={timed} />
            ))}
            {shown.length === 0 && (
              <tr>
                <td colSpan={8} className="muted">
                  No calls match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="row small muted" style={{ marginTop: 10 }}>
        <span>
          <span className="swatch" style={{ background: "var(--s3)" }} />
          Waiting for the first token
        </span>
        <span>
          <span className="swatch" style={{ background: "var(--accent)" }} />
          Generating
        </span>
        <span>Gaps are tools running, or you deciding.</span>
      </div>
    </section>
  );
}

function Row({ call: c, t0, span, timed }: { call: ModelCall; t0: number; span: number; timed: boolean }) {
  const left = timed ? ((startedAt(c) - t0) / span) * 100 : 0;
  const width = timed ? Math.max(((c.seconds * 1000) / span) * 100, 0.5) : 0;
  const wait = c.firstTokenSeconds !== null && c.seconds ? (c.firstTokenSeconds / c.seconds) * 100 : 0;
  return (
    <tr>
      <td className="num mono muted">{c.n}</td>
      <td>
        <span className={c.toolError ? "status-failed" : ""}>{askedFor(c)}</span>
        {c.subagent && <div className="muted small">subagent: {c.subagent}</div>}
      </td>
      <td className="mono small">{c.stopReason}</td>
      <td className="num mono">{tokens(contextTotal(c.context))}</td>
      <td className="num mono">{tokens(c.cacheRead)}</td>
      <td className="num mono">{tokens(c.cacheWrite)}</td>
      <td className="num mono">{tokens(c.output)}</td>
      <td className="wf-time">
        {timed ? (
          <div className="wf-track" title={`${seconds(c.seconds)}${c.firstTokenSeconds !== null ? `, first token after ${seconds(c.firstTokenSeconds)}` : ""}`}>
            <div className="wf-bar" style={{ left: `${left}%`, width: `${width}%` }}>
              <span style={{ width: `${wait}%`, background: "var(--s3)" }} />
              <span style={{ flex: 1, background: "var(--accent)" }} />
            </div>
          </div>
        ) : null}
        <span className="mono small muted">{seconds(c.seconds)}</span>
      </td>
    </tr>
  );
}
