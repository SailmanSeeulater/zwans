"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Attempt, type Comparison, type Report } from "@/lib/api";
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
  return (
    <main className="page page-wide">
      <p>
        <Link href="/evals/">← Evals</Link>
      </p>
      <h1>
        {a} → {b}
      </h1>
      <p className="muted">
        B minus A, each with a 95% interval from a paired bootstrap over tasks. Significant means the interval leaves
        out zero.
      </p>
      {error && <div className="notice notice-bad">{error}</div>}
      {comparison && (
        <>
          <table className="table" style={{ marginTop: 12 }}>
            <thead>
              <tr>
                <th>Metric</th>
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
          <p className="muted">
            {comparison.tasks.length} tasks in both
            {comparison.only_in_a.length > 0 && ` · only in A: ${comparison.only_in_a.join(", ")}`}
            {comparison.only_in_b.length > 0 && ` · only in B: ${comparison.only_in_b.join(", ")}`}
          </p>

          <h2>Tasks whose pass rate changed</h2>
          {changed.length === 0 && <p className="muted">None.</p>}
          {changed.length > 0 && (
            <table className="table">
              <tbody>
                {changed.map(([name, [before, after]]) => (
                  <tr key={name}>
                    <td>
                      <button className="button" onClick={() => setTask(name)} aria-pressed={task === name}>
                        {name}
                      </button>
                    </td>
                    <td className={after < before ? "status-failed" : "status-passed"}>
                      {pct(before)} → {pct(after)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="muted" style={{ marginTop: 10 }}>
            Or pick any task:{" "}
            <select className="select" value={task ?? ""} onChange={(e) => setTask(e.target.value || null)} aria-label="Task">
              <option value="">…</option>
              {comparison.tasks.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </p>
          {task && reportA && reportB && (
            <TaskDiff key={task} task={task} a={a} b={b} attemptsA={reportA.attempts} attemptsB={reportB.attempts} />
          )}
        </>
      )}
    </main>
  );
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
