"use client";

import Link from "next/link";
import type { RunListing } from "@/lib/api";
import { compareLink, findPair } from "@/lib/evalHints";
import { dollars, pct, seconds, tokens } from "@/lib/format";
import { contextTotal, latestTurnCall } from "@/lib/calls";
import { Markdown } from "../Markdown";
import { useApi } from "../useApi";
import type { InspectorProps } from "./Inspector";

/** Draft 13: each compaction, what it kept, and the summary the model wrote. */
export function CompactionTab({ data, status }: InspectorProps) {
  const { data: runs } = useApi<RunListing[]>("/api/evals");
  const compactAt = status?.compact_at ?? 200_000;
  const pair = runs ? findPair(runs, "default", "compact-20k") : null;
  const latest = latestTurnCall(data.calls);
  const now = latest ? contextTotal(latest.context) : 0;

  return (
    <div className="inspect-stack">
      {data.compactions.length === 0 && (
        <section className="panel glass">
          <h1 style={{ marginTop: 0 }}>No compaction yet</h1>
          <p className="muted">
            When the context passes {compactAt.toLocaleString()} tokens, Zwans asks the model to write handoff notes for
            the older messages, then carries on with the notes and the most recent messages word for word.
          </p>
          <div className="meter" style={{ marginTop: 12 }} role="img" aria-label="How close the context is to compacting">
            <span style={{ width: `${Math.min(now / compactAt, 1) * 100}%`, background: "var(--accent)" }} />
          </div>
          <p className="muted small">
            {tokens(now)} of {tokens(compactAt)} · {pct(now / compactAt)}
          </p>
        </section>
      )}

      {data.compactions.map((c, i) => {
        const next = data.calls.find((call) => call.n === c.beforeCall);
        const widest = Math.max(c.tokensBefore, c.tokensAfter, 1);
        return (
          <div key={i} className="inspect-grid">
            <section className="panel glass">
              <h1 style={{ marginTop: 0 }}>Compacted before call {c.beforeCall}</h1>
              <p className="muted">
                In turn {c.turn} the context reached about {c.tokensBefore.toLocaleString()} tokens, past the{" "}
                {compactAt.toLocaleString()} limit, so Zwans asked the model to summarize the older messages.
              </p>
              <div className="squeeze">
                <span className="stat-label">Before</span>
                <div className="squeeze-bar" style={{ width: `${(c.tokensBefore / widest) * 100}%` }}>
                  <span style={{ flex: 3, background: "var(--s3)" }}>Older messages</span>
                  <span style={{ flex: 1, background: "var(--s4)", color: "var(--on-s4)" }}>Recent</span>
                </div>
                <span className="mono">{c.tokensBefore.toLocaleString()}</span>
                <span className="stat-label">After</span>
                <div className="squeeze-bar" style={{ width: `${(c.tokensAfter / widest) * 100}%` }}>
                  <span style={{ flex: 1, background: "var(--accent)", color: "var(--accent-ink)" }}>Summary</span>
                  <span style={{ flex: 1, background: "var(--s4)", color: "var(--on-s4)" }}>Recent</span>
                </div>
                <span className="mono">{c.tokensAfter.toLocaleString()}</span>
              </div>
              <p className="muted small">
                {c.call
                  ? `The summary took 1 model call: ${seconds(c.call.seconds)}, ${dollars(c.call.dollars)}. `
                  : ""}
                The cached prefix changes here, so the next call writes the cache again
                {next ? `: call ${next.n} wrote ${tokens(next.cacheWrite)} tokens and read ${tokens(next.cacheRead)}.` : "."}
              </p>
            </section>
            <aside className="panel glass inspect-side">
              <h3>The summary the model wrote</h3>
              {c.summary ? <Markdown text={c.summary} /> : <p className="muted">Not recorded for this session.</p>}
            </aside>
          </div>
        );
      })}

      {pair && (
        <section className="panel glass">
          <h3>From your evals</h3>
          <p className="small">
            On {pair[0].tasks.length} tasks with {pair[0].model}, compacting at 20,000 tokens cost{" "}
            <b>{dollars(pair[1].summary.dollars)}</b> against <b>{dollars(pair[0].summary.dollars)}</b>, and took{" "}
            {Math.round(pair[1].summary.mean_seconds)} s per task against {Math.round(pair[0].summary.mean_seconds)} s. Pass
            rates: {pct(pair[1].summary.pass_rate)} and {pct(pair[0].summary.pass_rate)}.
          </p>
          <Link className="button" href={compareLink(pair[0].name, pair[1].name)}>
            Open the comparison
          </Link>
        </section>
      )}
    </div>
  );
}
