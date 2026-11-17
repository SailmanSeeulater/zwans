"use client";

import Link from "next/link";
import type { RunListing } from "@/lib/api";
import { cacheHitRate, costParts, uncachedCost, type CostParts } from "@/lib/calls";
import { compareLink, findPair } from "@/lib/evalHints";
import { dollars, pct } from "@/lib/format";
import { useApi } from "../useApi";
import { Empty, type InspectorProps } from "./Inspector";

const KINDS: { key: keyof CostParts; name: string; color: string }[] = [
  { key: "output", name: "Output", color: "var(--accent)" },
  { key: "cacheWrite", name: "Cache writes", color: "var(--s2)" },
  { key: "cacheRead", name: "Cache reads", color: "var(--s3)" },
  { key: "input", name: "Fresh input", color: "var(--s4)" },
];

const add = (a: CostParts, b: CostParts): CostParts => ({
  input: a.input + b.input,
  cacheWrite: a.cacheWrite + b.cacheWrite,
  cacheRead: a.cacheRead + b.cacheRead,
  output: a.output + b.output,
});
const ZERO: CostParts = { input: 0, cacheWrite: 0, cacheRead: 0, output: 0 };
const sum = (p: CostParts) => p.input + p.cacheWrite + p.cacheRead + p.output;

/** Draft 12: what the session cost, what it would have cost without the cache, and why. */
export function CostCache({ data, status }: InspectorProps) {
  const { data: runs } = useApi<RunListing[]>("/api/evals");
  const priced = data.calls.filter((c) => c.prices);
  if (!data.calls.length) return <Empty>No model calls yet, so nothing has cost anything.</Empty>;

  const total = priced.reduce((s, c) => add(s, costParts(c)!), ZERO);
  const uncached = priced.reduce((s, c) => s + (uncachedCost(c) ?? 0), 0);
  const turns = [...new Set(data.calls.map((c) => c.turn))].map((turn) => ({
    turn,
    parts: priced.filter((c) => c.turn === turn).reduce((s, c) => add(s, costParts(c)!), ZERO),
  }));
  const biggest = Math.max(...turns.map((t) => sum(t.parts)), 1e-9);
  const prices = priced[0]?.prices;
  const pair = runs ? findPair(runs, "default", "cache-off") : null;

  const times = (x: number) => `${Number(x.toPrecision(3))}×`;
  const why: Record<keyof CostParts, string> = {
    output: `What the model wrote, thinking included${prices ? `: ${times(prices.output / prices.input)} the input price` : ""}`,
    cacheWrite: `The first time a prefix is sent, it's stored${prices ? ` at ${times(prices.cache_write / prices.input)} the input price` : ""}`,
    cacheRead: `Sending that prefix again${prices ? `, at ${times(prices.cache_read / prices.input)} the input price` : ""}`,
    input: "New tokens after the last cache breakpoint, at the full price",
  };

  return (
    <div className="inspect-stack">
      <div className="kpis">
        <div className="panel glass">
          <span className="stat-label">This session</span>
          <span className="stat-value">{dollars(status?.dollars ?? sum(total))}</span>
        </div>
        <div className="panel glass">
          <span className="stat-label">With caching off</span>
          <span className="stat-value">≈ {dollars(uncached)}</span>
        </div>
        <div className="panel glass">
          <span className="stat-label">Cache hit rate</span>
          <span className="stat-value">{pct(cacheHitRate(data.calls))}</span>
        </div>
        <div className="panel glass">
          <span className="stat-label">Model calls</span>
          <span className="stat-value">{data.calls.length}</span>
        </div>
      </div>

      <div className="inspect-grid">
        <section className="panel glass">
          <h2 style={{ marginTop: 0 }}>Cost per turn</h2>
          <div className="bars" role="img" aria-label="Cost of each turn, by kind">
            {turns.map((t) => (
              <div key={t.turn} className="bar-col" title={`Turn ${t.turn}: ${dollars(sum(t.parts))}`}>
                <div className="bar-stack" style={{ height: `${(sum(t.parts) / biggest) * 100}%` }}>
                  {KINDS.map((k) => (
                    <span key={k.key} style={{ flex: t.parts[k.key] / (sum(t.parts) || 1), background: k.color }} />
                  ))}
                </div>
                <span className="mono small muted">{t.turn}</span>
              </div>
            ))}
          </div>
          <div className="row small muted">
            {KINDS.map((k) => (
              <span key={k.key}>
                <span className="swatch" style={{ background: k.color }} />
                {k.name}
              </span>
            ))}
          </div>
        </section>

        <aside className="panel glass inspect-side">
          <h2 style={{ marginTop: 0 }}>Where the money went</h2>
          {KINDS.map((k) => (
            <div key={k.key} className="money-row">
              <span className="swatch" style={{ background: k.color }} />
              <span style={{ flex: 1 }}>
                {k.name}
                <span className="muted small" style={{ display: "block" }}>
                  {why[k.key]}
                </span>
              </span>
              <span className="mono">{dollars(total[k.key])}</span>
            </div>
          ))}
          {pair && (
            <>
              <h3 style={{ marginTop: 14 }}>From your evals</h3>
              <p className="small">
                On {pair[0].tasks.length} tasks with {pair[0].model}, turning the cache off took a run from{" "}
                <b>{dollars(pair[0].summary.dollars)}</b> to <b>{dollars(pair[1].summary.dollars)}</b>, with pass rates of{" "}
                {pct(pair[0].summary.pass_rate)} and {pct(pair[1].summary.pass_rate)}.
              </p>
              <Link className="button" href={compareLink(pair[0].name, pair[1].name)}>
                Open the comparison
              </Link>
            </>
          )}
        </aside>
      </div>
    </div>
  );
}
