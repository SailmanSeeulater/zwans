"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Attempt, type Comparison, type Difference, type Report } from "@/lib/api";
import { align, firstDivergence, toSteps, type Row, type Step } from "@/lib/align";
import type { RawEvent } from "@/lib/events";
import { TokenMissing, useApi, useHasToken } from "./useApi";

const pct = (x: number) => `${Math.round(x * 100)}%`;

function formatMetric(metric: string, value: number, signed = false): string {
  const sign = signed && value > 0 ? "+" : "";
  if (metric === "pass rate") return `${sign}${Math.round(value * 100)}${signed ? " pts" : "%"}`;
  if (metric === "dollars") return `${sign}${value.toFixed(4)}`;
  return `${sign}${value.toFixed(1)}`;
}

export function CompareView() {
  const params = useSearchParams();
  const a = params.get("a") ?? "";
  const b = params.get("b") ?? "";
  const hasToken = useHasToken();
  const ready = hasToken && a && b;
  const { data: comparison, error } = useApi<Comparison>(
    ready ? `/api/evals/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}` : null,
  );
  const { data: reportA } = useApi<Report>(ready ? `/api/evals/${encodeURIComponent(a)}` : null);
  const { data: reportB } = useApi<Report>(ready ? `/api/evals/${encodeURIComponent(b)}` : null);
  const [task, setTask] = useState<string | null>(null);

  const changed = useMemo(() => {
    if (!comparison) return [];
    return Object.entries(comparison.task_pass_rates)
      .filter(([, [before, after]]) => before !== after)
      .sort(([, x], [, y]) => x[1] - x[0] - (y[1] - y[0]));
  }, [comparison]);

  if (hasToken === false) {
    return (
      <main className="page">
        <TokenMissing />
      </main>
    );
  }
  const nameA = reportA?.config.name ?? a;
  const nameB = reportB?.config.name ?? b;
  const repeats = reportA?.repeats ?? 1;
  const metric = (name: string) => comparison?.differences.find((d) => d.metric === name);

  return (
    <main className="page page-wide">
      <Link href="/evals/" className="back-link">
        <ChevronLeft size={14} aria-hidden="true" /> Eval runs
      </Link>
      <h1>
        {nameA} <span className="muted">against</span> {nameB}
      </h1>
      {reportA && (
        <p className="muted">
          {a} → {b} · {reportA.model} · {comparison?.tasks.length ?? "…"} tasks · {repeats} attempts each
        </p>
      )}
      {error && <div className="notice notice-bad">{error}</div>}
      {comparison && reportA && reportB && (
        <>
          <div className="kpis">
            <Kpi label="Pass rate" a={pct(reportA.summary.pass_rate)} b={pct(reportB.summary.pass_rate)} d={metric("pass rate")} />
            <Kpi label="Cost of the run" a={`$${reportA.summary.dollars.toFixed(2)}`} b={`$${reportB.summary.dollars.toFixed(2)}`} d={metric("dollars")} />
            <Kpi label="Seconds per task" a={reportA.summary.mean_seconds.toFixed(0)} b={reportB.summary.mean_seconds.toFixed(0)} d={metric("seconds")} />
            <Kpi label="Model calls per task" a={reportA.summary.mean_model_calls.toFixed(1)} b={reportB.summary.mean_model_calls.toFixed(1)} d={metric("model calls")} />
          </div>

          <div className="inspect-grid">
            <section className="panel glass">
              <h2 style={{ marginTop: 0 }}>Attempts passed, per task</h2>
              <TaskDots rates={comparison.task_pass_rates} repeats={repeats} nameA={nameA} nameB={nameB} onPick={setTask} />
            </section>
            <aside className="panel glass inspect-side">
              <h3>Reading it</h3>
              {reading(comparison, reportA, reportB, nameA, nameB).map((line) => (
                <p key={line} className="small">
                  {line}
                </p>
              ))}
            </aside>
          </div>

          <details className="panel glass" style={{ marginTop: 12 }}>
            <summary style={{ cursor: "pointer", fontWeight: 600 }}>Every metric, with 95% intervals</summary>
            <p className="muted small">
              B minus A, each with a 95% interval from a paired bootstrap over tasks. Significant means the interval
              leaves out zero.
            </p>
            <table className="table">
              <thead>
                <tr>
                  <th>Metric, per task</th>
                  <th className="num">A</th>
                  <th className="num">B</th>
                  <th className="num">B − A</th>
                  <th className="num">95% interval</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {comparison.differences.map((d) => (
                  <tr key={d.metric} className={d.significant ? "significant" : ""}>
                    <td>{d.metric}</td>
                    <td className="num">{formatMetric(d.metric, d.a)}</td>
                    <td className="num">{formatMetric(d.metric, d.b)}</td>
                    <td className="num">{formatMetric(d.metric, d.delta, true)}</td>
                    <td className="num">
                      [{formatMetric(d.metric, d.low, true)}, {formatMetric(d.metric, d.high, true)}]
                    </td>
                    <td>{d.significant ? "significant" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted small">
              {comparison.tasks.length} tasks in both
              {comparison.only_in_a.length > 0 && ` · only in A: ${comparison.only_in_a.join(", ")}`}
              {comparison.only_in_b.length > 0 && ` · only in B: ${comparison.only_in_b.join(", ")}`}
            </p>
          </details>

          <h2>Step by step</h2>
          <p className="muted">
            Pick a task to line up one attempt from each run and find where they part ways.{" "}
            <select className="select" value={task ?? ""} onChange={(e) => setTask(e.target.value || null)} aria-label="Task">
              <option value="">Choose a task…</option>
              {changed.length > 0 && (
                <optgroup label="Pass rate changed">
                  {changed.map(([name]) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </optgroup>
              )}
              <optgroup label="All tasks">
                {comparison.tasks.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </optgroup>
            </select>
          </p>
          {task && (
            <TaskDiff key={task} task={task} a={a} b={b} attemptsA={reportA.attempts} attemptsB={reportB.attempts} />
          )}
        </>
      )}
    </main>
  );
}

function Kpi({ label, a, b, d }: { label: string; a: string; b: string; d?: Difference }) {
  return (
    <div className="panel glass">
      <span className="stat-label">{label}</span>
      <span className="kpi-change">
        <span className="muted">{a}</span> → <span className="stat-value">{b}</span>
      </span>
      {d && (
        <span className={`small ${d.significant ? "significant" : "muted"}`}>
          {formatMetric(d.metric, d.delta, true)} per task · {d.significant ? "significant" : "within noise"}
        </span>
      )}
    </div>
  );
}

/** Each task's passes in A and B on one scale, joined by a line. */
function TaskDots(props: {
  rates: Record<string, [number, number]>;
  repeats: number;
  nameA: string;
  nameB: string;
  onPick: (task: string) => void;
}) {
  const rows = Object.entries(props.rates).sort(([x], [y]) => x.localeCompare(y));
  const at = (rate: number) => `${rate * 100}%`;
  return (
    <div className="dots">
      <div className="dots-row dots-axis">
        <span />
        <div className="dots-track">
          <span style={{ left: "0%" }}>0</span>
          <span style={{ left: "50%" }}>{props.repeats / 2}</span>
          <span style={{ left: "100%" }}>{props.repeats}</span>
        </div>
      </div>
      {rows.map(([task, [ra, rb]]) => (
        <button key={task} className="dots-row" onClick={() => props.onPick(task)} title={`${task}: ${Math.round(ra * props.repeats)} → ${Math.round(rb * props.repeats)}`}>
          <span className="mono small dots-name">{task}</span>
          <div className="dots-track">
            {ra !== rb && (
              <span
                className={`dots-line ${rb < ra ? "dots-worse" : "dots-better"}`}
                style={{ left: at(Math.min(ra, rb)), width: at(Math.abs(rb - ra)) }}
              />
            )}
            <span className="dot dot-a" style={{ left: at(ra) }} />
            <span className="dot dot-b" style={{ left: at(rb) }} />
          </div>
        </button>
      ))}
      <div className="row small muted" style={{ marginTop: 8 }}>
        <span>
          <span className="dot-key dot-a" /> {props.nameA}
        </span>
        <span>
          <span className="dot-key dot-b" /> {props.nameB}
        </span>
      </div>
    </div>
  );
}

/** A plain reading of the comparison, from its own numbers. */
function reading(c: Comparison, ra: Report, rb: Report, nameA: string, nameB: string): string[] {
  const lines: string[] = [];
  const costRatio = rb.summary.dollars / (ra.summary.dollars || 1);
  const cost = c.differences.find((d) => d.metric === "dollars");
  if (costRatio > 1.15 || costRatio < 0.87) {
    lines.push(
      `${nameB} cost ${costRatio > 1 ? `${costRatio.toFixed(1)}× as much as` : `${Math.round((1 - costRatio) * 100)}% less than`} ${nameA}${cost?.significant ? ", a real difference" : ", though within noise"}.`,
    );
  } else {
    lines.push("The two cost about the same.");
  }
  const passDelta = rb.summary.passed - ra.summary.passed;
  const moved = Object.entries(c.task_pass_rates).filter(([, [x, y]]) => x !== y);
  const pass = c.differences.find((d) => d.metric === "pass rate");
  if (passDelta === 0 && moved.length === 0) {
    lines.push("Every task passed exactly as often in both.");
  } else {
    lines.push(
      `${Math.abs(passDelta)} ${Math.abs(passDelta) === 1 ? "attempt" : "attempts"} ${passDelta >= 0 ? "more" : "fewer"} passed, out of ${ra.summary.attempts}, spread over ${moved.length} ${moved.length === 1 ? "task" : "tasks"}. ${pass?.significant ? "That is outside the noise." : "That is within the noise: tasks that flip between runs can do this on their own."}`,
    );
  }
  if (!pass?.significant && moved.length > 0) {
    lines.push(`To be sure, rerun ${moved.map(([t]) => t).join(", ")} with more repeats.`);
  }
  return lines;
}

/** The attempt to show by default: on a regression, a pass in A against a failure in B. */
function pick(attempts: Attempt[], prefer: Attempt["status"]): Attempt | undefined {
  return attempts.find((x) => x.status === prefer) ?? attempts[0];
}

function TaskDiff(props: { task: string; a: string; b: string; attemptsA: Attempt[]; attemptsB: Attempt[] }) {
  const inA = props.attemptsA.filter((x) => x.task === props.task && x.transcript);
  const inB = props.attemptsB.filter((x) => x.task === props.task && x.transcript);
  const [fileA, setFileA] = useState(pick(inA, "passed")?.transcript ?? "");
  const [fileB, setFileB] = useState(pick(inB, "failed")?.transcript ?? "");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const first = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!fileA || !fileB) return;
    const load = (run: string, file: string) =>
      api<RawEvent[]>(`/api/evals/${encodeURIComponent(run)}/transcripts/${encodeURIComponent(file)}`);
    let stale = false;
    Promise.all([load(props.a, fileA), load(props.b, fileB)])
      .then(([eventsA, eventsB]) => {
        if (!stale) setRows(align(toSteps(eventsA), toSteps(eventsB)));
      })
      .catch((err: unknown) => {
        if (!stale) setProblem(err instanceof Error ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [props.a, props.b, fileA, fileB]);

  const divergence = rows ? firstDivergence(rows) : -1;
  useEffect(() => {
    first.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [rows]);

  const chooser = (attempts: Attempt[], value: string, set: (v: string) => void, label: string) => (
    <select className="select" value={value} onChange={(e) => set(e.target.value)} aria-label={label}>
      {attempts.map((x) => (
        <option key={x.transcript} value={x.transcript}>
          #{x.repeat} {x.status}
        </option>
      ))}
    </select>
  );

  return (
    <section>
      <h2>{props.task}: the two transcripts, step by step</h2>
      <div className="row" style={{ marginBottom: 10 }}>
        A {chooser(inA, fileA, setFileA, "Attempt in A")} B {chooser(inB, fileB, setFileB, "Attempt in B")}
        {rows && (
          <span className="muted">
            {divergence === -1 ? "The two runs took the same steps." : `They first part ways at step ${divergence + 1}.`}
          </span>
        )}
      </div>
      {problem && <div className="notice notice-bad">{problem}</div>}
      {rows && (
        <div className="steps">
          <div className="label">#</div>
          <div className="label">{props.a}</div>
          <div className="label">{props.b}</div>
          {rows.map((row, i) => {
            const style = i === divergence ? "step-first" : row.same ? "" : "step-differs";
            return (
              <div key={i} style={{ display: "contents" }}>
                <div className={`step-index ${style}`} ref={i === divergence ? first : undefined}>
                  {i + 1}
                </div>
                <StepCell step={row.a} className={style} />
                <StepCell step={row.b} className={style} />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function StepCell({ step, className }: { step: Step | null; className: string }) {
  if (!step) return <div className={`step step-gap ${className}`}>·</div>;
  return (
    <div className={`step ${step.isError ? "step-error" : ""} ${className}`}>
      <details>
        <summary>{step.kind === "text" ? `“${step.label}”` : step.label}</summary>
        <pre className="raw">{step.detail}</pre>
      </details>
    </div>
  );
}
