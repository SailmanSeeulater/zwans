"use client";

import { Maximize2 } from "lucide-react";
import type { SessionStatus } from "@/lib/api";
import { askedFor, cacheHitRate, contextTotal, latestTurnCall, type UnderTheHood as Data } from "@/lib/calls";
import { dollars, pct, seconds, tokens } from "@/lib/format";
import type { InspectorTab } from "./inspector/Inspector";

export const PARTS = [
  { key: "system", label: "System prompt", color: "var(--s1)", ink: "var(--on-s1)" },
  { key: "tools", label: "Tool definitions", color: "var(--s2)", ink: "var(--on-s2)" },
  { key: "messages", label: "Messages", color: "var(--s3)", ink: "var(--on-s3)" },
  { key: "tool_results", label: "Tool results", color: "var(--s4)", ink: "var(--on-s4)" },
] as const;

interface Props {
  data: Data;
  status: SessionStatus | null;
  onOpen: (tab: InspectorTab) => void;
}

/** The right-hand panel: what the model is being sent, call by call, and what it costs. */
export function UnderTheHood({ data, status, onOpen }: Props) {
  const { calls, compactions } = data;
  const latest = latestTurnCall(calls);
  const total = latest ? contextTotal(latest.context) : 0;
  const compactAt = status?.compact_at ?? 200_000;
  const thisTurn = calls.filter((c) => c.turn === (latest?.turn ?? 0));

  return (
    <aside className="inspector glass" aria-label="Under the hood">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2>Under the hood</h2>
        {status && (
          <span className={status.demo ? "pill" : "pill pill-quiet"}>{status.demo ? "Scripted model" : status.model}</span>
        )}
      </div>

      <button className="hood-card" onClick={() => onOpen("context")} aria-label="Open the context map">
        <h3>What&apos;s in context</h3>
        {latest ? (
          <>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
              <span className="stat-value">{total.toLocaleString()}</span>
              <span className="muted">tokens</span>
            </div>
            <div className="meter" role="img" aria-label="How the context divides">
              {PARTS.map((p) => (
                <span key={p.key} style={{ width: `${(latest.context[p.key] / (total || 1)) * 100}%`, background: p.color }} />
              ))}
            </div>
            <div className="legend">
              {PARTS.map((p) => (
                <span key={p.key}>
                  <span className="swatch" style={{ background: p.color }} />
                  {p.label} <span className="mono muted">{tokens(latest.context[p.key])}</span>
                </span>
              ))}
            </div>
            <p className="muted small">
              {pct(total / compactAt)} of the way to a compaction, which comes at {compactAt.toLocaleString()} tokens.
            </p>
          </>
        ) : (
          <p className="muted small">Nothing yet. After the first model call, this shows what the request held.</p>
        )}
      </button>

      <button className="hood-card" onClick={() => onOpen("calls")} aria-label="Open the call waterfall">
        <h3>Model calls {latest ? `in turn ${latest.turn}` : ""}</h3>
        {thisTurn.length === 0 && <p className="muted small">None yet.</p>}
        {thisTurn.map((c) => (
          <div key={c.n} className="call-row">
            <span className="mono muted">#{c.n}</span>
            <span className={`call-row-name ${c.toolError ? "status-failed" : ""}`}>{askedFor(c)}</span>
            <span className="mono muted">{seconds(c.seconds)}</span>
            <span className="call-row-sub">
              in {tokens(c.input + c.cacheWrite)} · cached {tokens(c.cacheRead)} · out {tokens(c.output)}
            </span>
          </div>
        ))}
      </button>

      <button className="hood-card" onClick={() => onOpen("cost")} aria-label="Open cost and cache">
        <div className="hood-pair">
          <div>
            <h3>Cost so far</h3>
            <span className="stat-value">{dollars(status?.dollars ?? 0)}</span>
          </div>
          <div>
            <h3>Cache hit rate</h3>
            <span className="stat-value">{calls.length ? pct(cacheHitRate(calls)) : "–"}</span>
          </div>
        </div>
      </button>

      {compactions.length > 0 && (
        <button className="hood-card" onClick={() => onOpen("compaction")} aria-label="Open compaction">
          <h3>Compaction</h3>
          <p className="small">
            Compacted {compactions.length === 1 ? "once" : `${compactions.length} times`}, last from{" "}
            {tokens(compactions.at(-1)!.tokensBefore)} to {tokens(compactions.at(-1)!.tokensAfter)} tokens.
          </p>
        </button>
      )}

      <div className="sidebar-spacer" />
      <button className="button" onClick={() => onOpen("context")}>
        <Maximize2 size={14} aria-hidden="true" />
        Open the inspector
      </button>
    </aside>
  );
}
