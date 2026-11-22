"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { TokenMissing, useApi, useHasToken } from "@/components/useApi";
import type { RunListing } from "@/lib/api";
import { pct, plural, spent } from "@/lib/format";

/** Runs of the same task set belong on one line of the chart. A set is named by its size
 * and its first task. */
function suiteOf(run: RunListing): string {
  const more = run.tasks.length > 1 ? ", …" : "";
  return `${plural(run.tasks.length, "task")}: ${run.tasks[0] ?? ""}${more}`;
}

export default function RunsPage() {
  const hasToken = useHasToken();
  const { data: runs, error } = useApi<RunListing[]>(hasToken ? "/api/evals" : null);
  const [picked, setPicked] = useState<string[]>([]);

  const toggle = (name: string) =>
    setPicked((current) =>
      current.includes(name) ? current.filter((n) => n !== name) : [...current, name],
    );

  if (hasToken === false) {
    return (
      <main className="page">
        <h1>Evals</h1>
        <TokenMissing />
      </main>
    );
  }

  const [a, b] = picked.length === 2 ? picked : [];
  return (
    <main className="page page-wide">
      <h1>Evals</h1>
      <p className="muted">
        Runs from <code>evals/reports/</code>. Tick two to compare them, or several for a task matrix.
      </p>
      {error && <div className="notice notice-bad">{error}</div>}
      {!runs && !error && <p className="muted">Loading…</p>}
      {runs && runs.length === 0 && <p className="muted">No reports yet. Run <code>zwans eval run</code>.</p>}
      {runs && runs.length > 0 && (
        <>
          <h2>Pass rate over time</h2>
          <History runs={runs} />
          <div className="row" style={{ margin: "20px 0 10px" }}>
            <Link
              className={`button button-primary ${a && b ? "" : "disabled"}`}
              href={a && b ? `/evals/compare/?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}` : "#"}
              aria-disabled={!(a && b)}
              title={a && b ? undefined : "Tick exactly two runs in the table first"}
              onClick={(e) => {
                if (!(a && b)) e.preventDefault();
              }}
            >
              Compare {a && b ? `${a} → ${b}` : "two runs"}
            </Link>
            <Link
              className="button"
              href={picked.length >= 2 ? `/evals/matrix/?runs=${picked.map(encodeURIComponent).join(",")}` : "/evals/matrix/"}
            >
              {picked.length >= 2 ? `Task matrix of ${picked.length} runs` : "Task matrix"}
            </Link>
            <Link className="button" href="/evals/leaderboard/">
              Leaderboard
            </Link>
            {picked.length > 0 && (
              <button className="button button-quiet" onClick={() => setPicked([])}>
                Clear
              </button>
            )}
          </div>
          <table className="table">
            <thead>
              <tr>
                <th />
                <th>Run</th>
                <th>Agent, model, effort</th>
                <th>Config</th>
                <th>Started</th>
                <th className="num">Passed</th>
                <th className="num">Spent</th>
                <th className="num">Model calls</th>
                <th className="num">Seconds</th>
              </tr>
            </thead>
            <tbody>
              {[...runs].reverse().map((run) => (
                <tr key={run.name}>
                  <td>
                    <input
                      type="checkbox"
                      aria-label={`Compare ${run.name}`}
                      checked={picked.includes(run.name)}
                      onChange={() => toggle(run.name)}
                    />
                  </td>
                  <td>
                    <Link href={`/evals/run/?name=${encodeURIComponent(run.name)}`}>{run.name}</Link>
                    <div className="muted" style={{ fontSize: 13 }}>
                      {suiteOf(run)} × {run.repeats}
                    </div>
                  </td>
                  <td>
                    {run.agent} · {run.model} · {run.effort}
                    {run.executor !== "local" && <span className="muted"> · {run.executor}</span>}
                  </td>
                  <td>{run.config}</td>
                  <td>{run.started_at.replace("T", " ").slice(0, 16)}</td>
                  <td className="num">
                    {run.summary.passed}/{run.summary.attempts} ({pct(run.summary.pass_rate)})
                  </td>
                  <td className="num">{spent(run.summary.dollars)}</td>
                  <td className="num">{run.summary.mean_model_calls.toFixed(1)}</td>
                  <td className="num">{run.summary.mean_seconds.toFixed(0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}

// The last two are fixed mid-tones that read on every theme, so six or seven task sets
// each get a colour of their own.
const SERIES_COLORS = ["var(--accent)", "var(--ok)", "var(--warn)", "var(--bad)", "var(--ink-2)", "#a06cd5", "#2aa3a3"];

function History({ runs }: { runs: RunListing[] }) {
  const width = 1000;
  const height = 220;
  const pad = { left: 44, right: 16, top: 14, bottom: 26 };
  const suites = useMemo(() => {
    const bySuite = new Map<string, RunListing[]>();
    for (const run of runs) {
      const key = suiteOf(run);
      bySuite.set(key, [...(bySuite.get(key) ?? []), run]);
    }
    return [...bySuite.entries()];
  }, [runs]);

  const x = (i: number) => pad.left + (runs.length === 1 ? 0.5 : i / (runs.length - 1)) * (width - pad.left - pad.right);
  const y = (rate: number) => pad.top + (1 - rate) * (height - pad.top - pad.bottom);
  const index = new Map(runs.map((run, i) => [run.name, i]));

  return (
    <div>
      <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Pass rate of each run over time">
        {[0, 0.25, 0.5, 0.75, 1].map((rate) => (
          <g key={rate}>
            <line className="grid" x1={pad.left} x2={width - pad.right} y1={y(rate)} y2={y(rate)} />
            <text x={pad.left - 8} y={y(rate) + 4} textAnchor="end">
              {pct(rate)}
            </text>
          </g>
        ))}
        {suites.map(([suite, list], s) => {
          const color = SERIES_COLORS[s % SERIES_COLORS.length];
          const points = list.map((run) => `${x(index.get(run.name) ?? 0)},${y(run.summary.pass_rate)}`);
          return (
            <g key={suite}>
              <polyline points={points.join(" ")} fill="none" stroke={color} strokeWidth={2} />
              {list.map((run) => (
                <circle key={run.name} cx={x(index.get(run.name) ?? 0)} cy={y(run.summary.pass_rate)} r={4} fill={color}>
                  <title>
                    {run.name}: {pct(run.summary.pass_rate)} ({run.model}, {run.config})
                  </title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      <div className="row" style={{ marginTop: 6, fontSize: 13 }}>
        {suites.map(([suite], s) => (
          <span key={suite} className="row" style={{ gap: 6 }}>
            <span style={{ width: 10, height: 10, borderRadius: 5, background: SERIES_COLORS[s % SERIES_COLORS.length] }} />
            {suite}
          </span>
        ))}
      </div>
    </div>
  );
}
