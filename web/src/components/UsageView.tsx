"use client";

import { useState } from "react";
import { dollars, plural, tokens } from "@/lib/format";
import {
  axisTicks,
  bucketLabel,
  KINDS,
  labelled,
  PERIODS,
  type Period,
  type Usage,
  type UsageBucket,
  type UsageTotal,
} from "@/lib/usage";
import { UsageCalendar } from "./UsageCalendar";
import { TokenMissing, useApi, useHasToken } from "./useApi";

type Measure = "tokens" | "dollars";
const REFRESH_MS = 15_000;

// The chart's drawing, in viewBox units.
const W = 900;
const H = 280;
const PAD = { left: 58, right: 14, top: 16, bottom: 30 };

/** Tokens and dollars across every session, by day, week, month and year. */
export function UsageView() {
  const hasToken = useHasToken();
  const { data, error } = useApi<Usage>(hasToken ? "/api/usage" : null, REFRESH_MS);
  const [period, setPeriod] = useState<Period>("day");
  const [measure, setMeasure] = useState<Measure>("tokens");

  if (hasToken === false) {
    return (
      <main className="page">
        <h1>Usage</h1>
        <TokenMissing />
      </main>
    );
  }

  const chosen = PERIODS.find((p) => p.id === period) ?? PERIODS[0]!;
  const buckets = data?.series[period] ?? [];
  const used = [...buckets].reverse().filter((b) => b.calls > 0);
  const all = data?.totals.all;

  return (
    <main className="page">
      <h1>Usage</h1>
      <p className="muted">
        Tokens and cost across every session and chat on this machine, deleted ones included, at today&apos;s prices.
        Models running on this machine cost nothing. Eval runs and rooms keep their own totals and aren&apos;t counted
        here.
      </p>
      {error && <div className="notice notice-bad">{error}</div>}
      {data && all && all.calls === 0 && (
        <div className="panel glass muted">Nothing yet. Once a session has made a model call, it shows up here.</div>
      )}

      {data && (
        <div className="usage-tiles">
          {PERIODS.map((p) => (
            <Tile key={p.id} label={p.current} total={data.totals[p.id]} />
          ))}
          <Tile label="All time" total={data.totals.all} since={data.first} />
        </div>
      )}

      {data && all && all.calls > 0 && (
        <>
          <div className="row usage-controls">
            <div className="segmented" role="radiogroup" aria-label="Group by">
              {PERIODS.map((p) => (
                <button key={p.id} role="radio" aria-checked={period === p.id} onClick={() => setPeriod(p.id)}>
                  {p.name}
                </button>
              ))}
            </div>
            <div className="segmented" role="radiogroup" aria-label="Show">
              <button role="radio" aria-checked={measure === "tokens"} onClick={() => setMeasure("tokens")}>
                Tokens
              </button>
              <button role="radio" aria-checked={measure === "dollars"} onClick={() => setMeasure("dollars")}>
                Cost
              </button>
            </div>
          </div>

          <Bars buckets={buckets} period={period} measure={measure} />

          {data.calendar && (
            <>
              <h2>The past year, day by day</h2>
              <UsageCalendar data={data.calendar} measure={measure} />
            </>
          )}

          <h2>What the tokens were, {chosen.current.toLowerCase()}</h2>
          <Split total={data.totals[period]} />

          <h2>By {chosen.id}</h2>
          <div className="table-scroll">
            <table className="table usage-table">
              <thead>
                <tr>
                  <th>{chosen.each}</th>
                  <th>Tokens</th>
                  {KINDS.map((k) => (
                    <th key={k.key}>{k.label}</th>
                  ))}
                  <th>Cost</th>
                  <th>Model calls</th>
                  <th>Sessions</th>
                </tr>
              </thead>
              <tbody>
                {used.map((b) => (
                  <tr key={b.start}>
                    <td>{bucketLabel(b.start, period)}</td>
                    <Numbers total={b} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {used.length < buckets.length && (
            <p className="muted small">
              {period === "year" ? "Years" : `The last ${buckets.length} ${chosen.name.toLowerCase()}`} with nothing used
              are left out.
            </p>
          )}

          <h2>By model, all time</h2>
          <div className="table-scroll">
            <table className="table usage-table">
              <thead>
                <tr>
                  <th>Model</th>
                  <th>Tokens</th>
                  {KINDS.map((k) => (
                    <th key={k.key}>{k.label}</th>
                  ))}
                  <th>Cost</th>
                  <th>Model calls</th>
                  <th>Sessions</th>
                </tr>
              </thead>
              <tbody>
                {data.models.map((m) => (
                  <tr key={m.model}>
                    <td className="mono">{m.model}</td>
                    <Numbers total={m} />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {all.unpriced_calls > 0 && (
            <p className="muted small">
              {plural(all.unpriced_calls, "call")} ran on a model with no known price, so they add tokens and no cost.
              Give a hosted model&apos;s price under <span className="mono">prices</span> in its provider&apos;s
              config.
            </p>
          )}
        </>
      )}
    </main>
  );
}

function Tile({ label, total, since }: { label: string; total: UsageTotal; since?: string | null }) {
  return (
    <div className="panel glass usage-tile">
      <span className="stat-label">{label}</span>
      <span className="stat-value" title={`${total.tokens.toLocaleString()} tokens`}>
        {tokens(total.tokens)}
      </span>
      <span className="muted small">
        tokens · {dollars(total.dollars)}
        <br />
        {plural(total.calls, "call")} in {plural(total.sessions, "session")}
        {since ? ` since ${since}` : ""}
      </span>
    </div>
  );
}

function Numbers({ total }: { total: UsageTotal }) {
  return (
    <>
      <td className="num">{total.tokens.toLocaleString()}</td>
      {KINDS.map((k) => (
        <td key={k.key} className="num">
          {total[k.key].toLocaleString()}
        </td>
      ))}
      <td className="num">{total.unpriced_calls === total.calls && total.calls > 0 ? "–" : dollars(total.dollars)}</td>
      <td className="num">{total.calls.toLocaleString()}</td>
      <td className="num">{total.sessions.toLocaleString()}</td>
    </>
  );
}

/** How a period's tokens divide into the four kinds: one bar, with its numbers beside it. */
function Split({ total }: { total: UsageTotal }) {
  if (total.tokens === 0) return <p className="muted small">Nothing used.</p>;
  return (
    <div className="panel glass">
      <div className="meter" role="img" aria-label="How the tokens divide">
        {KINDS.map((k) => (
          <span key={k.key} style={{ width: `${(total[k.key] / total.tokens) * 100}%`, background: k.color }} />
        ))}
      </div>
      <div className="legend">
        {KINDS.map((k) => (
          <span key={k.key}>
            <span className="swatch" style={{ background: k.color }} />
            {k.label} <span className="mono muted">{tokens(total[k.key])}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

/** One bar a bucket: its tokens or its cost. A single series, so one colour and no legend. */
function Bars({ buckets, period, measure }: { buckets: UsageBucket[]; period: Period; measure: Measure }) {
  const [hover, setHover] = useState<number | null>(null);
  const value = (b: UsageBucket) => (measure === "tokens" ? b.tokens : b.dollars);
  const show = (n: number) => (measure === "tokens" ? tokens(n) : dollars(n));
  const ticks = axisTicks(Math.max(0, ...buckets.map(value)));
  const top = ticks.at(-1) ?? 1;
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;
  const slot = plotW / Math.max(1, buckets.length);
  const barW = Math.min(46, Math.max(4, slot - 6));
  const y = (n: number) => PAD.top + plotH - (n / top) * plotH;
  const names = labelled(buckets.length);
  const active = hover !== null ? buckets[hover] : undefined;
  const what = measure === "tokens" ? "Tokens" : "Cost";

  return (
    <div className="usage-chart" onMouseLeave={() => setHover(null)}>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${what} by ${period}. The table below has the numbers.`}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end">
              {show(t)}
            </text>
          </g>
        ))}
        {buckets.map((b, i) => {
          const x = PAD.left + i * slot + (slot - barW) / 2;
          const height = Math.max(value(b) > 0 ? 2 : 0, (value(b) / top) * plotH);
          const r = Math.min(4, barW / 2, height);
          const base = PAD.top + plotH;
          return (
            <g key={b.start}>
              {height > 0 && (
                // Rounded at the top, square on the baseline.
                <path
                  className={hover === i ? "usage-bar usage-bar-on" : "usage-bar"}
                  d={`M${x},${base} V${base - height + r} Q${x},${base - height} ${x + r},${base - height} H${x + barW - r} Q${x + barW},${base - height} ${x + barW},${base - height + r} V${base} Z`}
                />
              )}
              {names.has(i) && (
                <text x={x + barW / 2} y={H - 10} textAnchor="middle">
                  {bucketLabel(b.start, period)}
                </text>
              )}
              {/* The whole column takes the pointer, so a short bar is as easy to hit as a tall one. */}
              <rect
                x={PAD.left + i * slot}
                y={PAD.top}
                width={slot}
                height={plotH + PAD.bottom}
                fill="transparent"
                tabIndex={0}
                aria-label={`${bucketLabel(b.start, period)}: ${b.tokens.toLocaleString()} tokens, ${dollars(b.dollars)}`}
                onMouseEnter={() => setHover(i)}
                onFocus={() => setHover(i)}
                onBlur={() => setHover(null)}
              />
            </g>
          );
        })}
      </svg>
      {active && hover !== null && (
        <div
          className="usage-tip glass"
          style={{ left: `${((PAD.left + (hover + 0.5) * slot) / W) * 100}%` }}
          data-side={hover > buckets.length / 2 ? "left" : "right"}
          role="status"
        >
          <strong>
            {period === "week" ? "Week of " : ""}
            {bucketLabel(active.start, period)}
          </strong>
          <span>
            {active.tokens.toLocaleString()} tokens · {dollars(active.dollars)}
          </span>
          {KINDS.map((k) => (
            <span key={k.key} className="muted">
              {k.label} {active[k.key].toLocaleString()}
            </span>
          ))}
          <span className="muted">
            {plural(active.calls, "call")} in {plural(active.sessions, "session")}
          </span>
        </div>
      )}
    </div>
  );
}
