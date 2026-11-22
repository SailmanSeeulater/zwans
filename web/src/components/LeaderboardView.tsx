"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import type { Leaderboard, LeaderRow } from "@/lib/api";
import { dollars, pct, plural } from "@/lib/format";
import { costScale, rateTicks } from "@/lib/leaderboard";
import { TokenMissing, useApi, useHasToken } from "./useApi";

const STANDING: Record<LeaderRow["standing"], string> = {
  best: "Top",
  level: "Not clearly different",
  behind: "Clearly behind",
  too_few_tasks: "Too few tasks to tell",
};
const SHOWN_RUNS = 3;

const keyOf = (row: LeaderRow) => [row.agent, row.model, row.effort, row.executor, row.config].join("|");
const whatRan = (row: LeaderRow) =>
  [row.agent, row.model, row.effort, ...(row.executor === "local" ? [] : [row.executor])].join(" · ");
const runLink = (name: string) => `/evals/run/?name=${encodeURIComponent(name)}`;

function setName(board: Leaderboard): string {
  const more = board.tasks.length > 1 ? ", …" : "";
  return `${plural(board.tasks.length, "task")}: ${board.tasks[0]}${more} (${plural(board.runs, "run")})`;
}

/** Everything run on one set of tasks, ranked: how often it passes, and what that costs. */
export function LeaderboardView() {
  const hasToken = useHasToken();
  const { data: boards, error } = useApi<Leaderboard[]>(hasToken ? "/api/evals/leaderboard" : null);
  const [chosen, setChosen] = useState(0);
  const [picked, setPicked] = useState<string[]>([]); // rows to compare, by key

  if (hasToken === false) {
    return (
      <main className="page">
        <h1>Leaderboard</h1>
        <TokenMissing />
      </main>
    );
  }

  const board = boards?.[Math.min(chosen, boards.length - 1)];
  const rows = board?.rows ?? [];
  const [a, b] = picked.map((key) => rows.find((row) => keyOf(row) === key));
  const toggle = (key: string) =>
    setPicked((current) => (current.includes(key) ? current.filter((k) => k !== key) : [...current, key].slice(-2)));

  return (
    <main className="page page-wide">
      <Link href="/evals/" className="back-link">
        <ChevronLeft size={14} aria-hidden="true" /> Eval runs
      </Link>
      <h1>Leaderboard</h1>
      <p className="muted">
        Runs of the same tasks, pooled by what ran and ranked by pass rate, then by cost. Only the same tasks compare
        fairly, so each set of tasks has its own board.
      </p>
      {error && <div className="notice notice-bad">{error}</div>}
      {!boards && !error && <p className="muted">Loading…</p>}
      {boards && boards.length === 0 && (
        <p className="muted">
          No reports yet. Run <code>zwans eval run</code>.
        </p>
      )}
      {boards && board && (
        <>
          <div className="row" style={{ margin: "14px 0" }}>
            <select
              className="select"
              value={boards.indexOf(board)}
              onChange={(e) => {
                setChosen(Number(e.target.value));
                setPicked([]);
              }}
              aria-label="Set of tasks"
            >
              {boards.map((each, i) => (
                <option key={each.tasks.join("|")} value={i}>
                  {setName(each)}
                </option>
              ))}
            </select>
            <Link
              className={`button ${a && b ? "button-primary" : "disabled"}`}
              href={
                a && b
                  ? `/evals/compare/?a=${encodeURIComponent(a.runs.at(-1)!)}&b=${encodeURIComponent(b.runs.at(-1)!)}`
                  : "#"
              }
              aria-disabled={!(a && b)}
              title={a && b ? "Compares each row's latest run" : "Tick two rows in the table first"}
              onClick={(e) => {
                if (!(a && b)) e.preventDefault();
              }}
            >
              Compare two rows
            </Link>
          </div>

          <Scatter rows={rows} />

          <div className="table-scroll" style={{ marginTop: 16 }}>
            <table className="table" style={{ minWidth: 820 }}>
              <thead>
                <tr>
                  <th />
                  <th className="num">#</th>
                  <th>What ran</th>
                  <th className="num">Passed</th>
                  <th className="num">95% range</th>
                  <th className="num">Cost per attempt</th>
                  <th className="num">Seconds</th>
                  <th className="num">Model calls</th>
                  <th>Against the top row</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr key={keyOf(row)}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`Compare ${whatRan(row)}, config ${row.config}`}
                        checked={picked.includes(keyOf(row))}
                        onChange={() => toggle(keyOf(row))}
                      />
                    </td>
                    <td className="num muted">{i + 1}</td>
                    <td>
                      {whatRan(row)}
                      <div className="muted" style={{ fontSize: 13 }}>
                        config {row.config} ·{" "}
                        {row.runs.slice(-SHOWN_RUNS).map((name, j) => (
                          <span key={name}>
                            {j > 0 && ", "}
                            <Link href={runLink(name)}>{name}</Link>
                          </span>
                        ))}
                        {row.runs.length > SHOWN_RUNS && ` and ${row.runs.length - SHOWN_RUNS} earlier`}
                      </div>
                    </td>
                    <td className="num">
                      {row.passed}/{row.attempts} ({pct(row.pass_rate)})
                    </td>
                    <td className="num" style={{ whiteSpace: "nowrap" }}>
                      {pct(row.low)} to {pct(row.high)}
                    </td>
                    <td className="num">{dollars(row.mean_dollars)}</td>
                    <td className="num">{row.mean_seconds.toFixed(0)}</td>
                    <td className="num">{row.mean_model_calls.toFixed(1)}</td>
                    <td>
                      {row.standing === "best" ? (
                        <span className="pill" title="Ranked first: the highest pass rate, then the lowest cost">
                          {STANDING.best}
                        </span>
                      ) : (
                        STANDING[row.standing]
                      )}
                      {row.frontier && row.standing !== "best" && (
                        <div className="muted" style={{ fontSize: 13 }}>
                          nothing cheaper passes as often
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small" style={{ marginTop: 10 }}>
            The range is where the true pass rate most likely lies, given how many attempts there were: few attempts,
            wide range. The last column compares each row with the top one, task by task. &ldquo;Not clearly
            different&rdquo; means that can&apos;t tell the two apart, so run more repeats before calling a winner.
            &ldquo;Clearly behind&rdquo; means it passes less often on enough of the same tasks that luck is an unlikely
            reason, even where the ranges overlap.
          </p>
        </>
      )}
    </main>
  );
}

const W = 1000;
const H = 300;
const PAD = { left: 52, right: 28, top: 34, bottom: 40 }; // the top leaves room for the axis title

/** Cost against pass rate, one numbered dot per row. Up and to the left is better. */
function Scatter({ rows }: { rows: LeaderRow[] }) {
  const scale = useMemo(() => costScale(rows.map((row) => row.mean_dollars)), [rows]);
  const rates = useMemo(() => rateTicks(rows.map((row) => row.pass_rate)), [rows]);
  const floor = rates[0] ?? 0;
  const x = (cost: number) => PAD.left + scale.at(cost) * (W - PAD.left - PAD.right);
  const y = (rate: number) => PAD.top + (1 - (Math.max(rate, floor) - floor) / (1 - floor)) * (H - PAD.top - PAD.bottom);
  const frontier = rows.filter((row) => row.frontier).sort((p, q) => p.mean_dollars - q.mean_dollars);

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label="Pass rate against cost per attempt, one dot per row of the table"
    >
      {rates.map((rate) => (
        <g key={rate}>
          <line className="grid" x1={PAD.left} x2={W - PAD.right} y1={y(rate)} y2={y(rate)} />
          <text x={PAD.left - 8} y={y(rate) + 4} textAnchor="end">
            {pct(rate)}
          </text>
        </g>
      ))}
      {scale.ticks.map((tick) => (
        <text key={tick} x={x(tick)} y={H - PAD.bottom + 16} textAnchor="middle">
          {dollars(tick)}
        </text>
      ))}
      <text x={W - PAD.right} y={H - 6} textAnchor="end">
        Cost per attempt{scale.log ? " (each step is a multiple)" : ""}
      </text>
      <text x={PAD.left} y={14}>
        Pass rate
      </text>
      {frontier.length > 1 && (
        <polyline
          points={frontier.map((row) => `${x(row.mean_dollars)},${y(row.pass_rate)}`).join(" ")}
          fill="none"
          stroke="var(--accent)"
          strokeWidth={1.5}
          strokeDasharray="5 4"
          opacity={0.7}
        />
      )}
      {rows.map((row, i) => (
        <g key={keyOf(row)}>
          <title>
            #{i + 1} {whatRan(row)}, config {row.config}: {pct(row.pass_rate)} ({pct(row.low)} to {pct(row.high)}),{" "}
            {dollars(row.mean_dollars)} per attempt
          </title>
          {/* The range the pass rate most likely lies in. */}
          <line
            x1={x(row.mean_dollars)}
            x2={x(row.mean_dollars)}
            y1={y(row.high)}
            y2={y(row.low)}
            stroke="var(--ink-2)"
            strokeWidth={1}
            opacity={0.45}
          />
          <circle
            cx={x(row.mean_dollars)}
            cy={y(row.pass_rate)}
            r={6}
            fill={row.frontier ? "var(--accent)" : "var(--raised)"}
            stroke={row.frontier ? "var(--accent)" : "var(--ink-2)"}
            strokeWidth={1.5}
          />
          {/* Numbers alternate sides, so two dots close together don't print over each other. */}
          <text
            x={x(row.mean_dollars) + (i % 2 ? -10 : 10)}
            y={y(row.pass_rate) + 4}
            textAnchor={i % 2 ? "end" : "start"}
            style={{ fill: "var(--ink)", fontWeight: 600 }}
          >
            {i + 1}
          </text>
        </g>
      ))}
    </svg>
  );
}
