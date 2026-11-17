"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, type Report, type RunListing } from "@/lib/api";
import { dollars, pct } from "@/lib/format";
import { TokenMissing, useApi, useHasToken } from "./useApi";

const suiteKey = (r: RunListing) => `${r.model}|${r.repeats}|${[...r.tasks].sort().join(",")}`;

/** The runs to show when none are named: the latest run's suite, up to six of its runs. */
export function defaultRuns(runs: RunListing[]): string[] {
  const latest = [...runs].reverse().find((r) => r.repeats > 1) ?? runs.at(-1);
  if (!latest) return [];
  return runs.filter((r) => suiteKey(r) === suiteKey(latest)).slice(-6).map((r) => r.name);
}

function tone(passed: number, attempts: number): string {
  if (attempts === 0) return "";
  if (passed === attempts) return "cell-ok";
  return passed / attempts > 0.5 ? "cell-warn" : "cell-bad";
}

/** Draft 16: tasks down the side, configs across the top, attempts passed in each cell. */
export function MatrixView() {
  const params = useSearchParams();
  const hasToken = useHasToken();
  const { data: runs } = useApi<RunListing[]>(hasToken ? "/api/evals" : null);
  const runsParam = params.get("runs");
  const names = useMemo(
    () => (runsParam ? runsParam.split(",").filter(Boolean) : runs ? defaultRuns(runs) : []),
    [runsParam, runs],
  );
  const [reports, setReports] = useState<Report[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!hasToken || names.length === 0) return;
    let stale = false;
    Promise.all(names.map((n) => api<Report>(`/api/evals/${encodeURIComponent(n)}`)))
      .then((r) => {
        if (!stale) setReports(r);
      })
      .catch((err: unknown) => {
        if (!stale) setProblem(err instanceof Error ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [hasToken, names]);

  if (hasToken === false) {
    return (
      <main className="page">
        <TokenMissing />
      </main>
    );
  }

  const tasks = reports ? [...new Set(reports.flatMap((r) => Object.keys(r.tasks)))].sort() : [];
  const configs = reports?.map((r, i) => {
    const name = r.config.name;
    const duplicate = reports.filter((x) => x.config.name === name).length > 1;
    return duplicate ? names[i]! : name;
  });

  return (
    <main className="page page-wide">
      <Link href="/evals/" className="back-link">
        <ChevronLeft size={14} aria-hidden="true" /> Eval runs
      </Link>
      <h1>Tasks × configs</h1>
      {reports && reports[0] && (
        <p className="muted">
          Attempts passed out of {reports[0].repeats} · {reports[0].model} · {tasks.length} tasks · {reports.length} runs
        </p>
      )}
      {problem && <div className="notice notice-bad">{problem}</div>}
      {runs && names.length === 0 && <p className="muted">No runs yet.</p>}

      {reports && configs && (
        <div className="inspect-grid">
          <section className="panel glass table-scroll">
            <table className="table matrix">
              <thead>
                <tr>
                  <th>Task</th>
                  {configs.map((c, i) => (
                    <th key={i} className="num">
                      <Link href={`/evals/run/?name=${encodeURIComponent(names[i]!)}`}>{c}</Link>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task}>
                    <td className="mono">{task}</td>
                    {reports.map((r, i) => {
                      const s = r.tasks[task];
                      return (
                        <td key={i} className="num">
                          {s ? (
                            <span className={`cell ${tone(s.passed, s.attempts)}`} title={`${s.passed} of ${s.attempts} passed`}>
                              {s.passed}
                            </span>
                          ) : (
                            <span className="muted">–</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <th>Passed</th>
                  {reports.map((r, i) => (
                    <td key={i} className="num mono">
                      {pct(r.summary.pass_rate)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <th>Cost</th>
                  {reports.map((r, i) => (
                    <td key={i} className="num mono">
                      {dollars(r.summary.dollars)}
                    </td>
                  ))}
                </tr>
              </tfoot>
            </table>
          </section>
          <aside className="panel glass inspect-side">
            <h3>Key</h3>
            <div className="key-list">
              <span>
                <span className="cell cell-ok">{reports[0]?.repeats}</span> Every attempt passed
              </span>
              <span>
                <span className="cell cell-warn">·</span> Some failed, under half
              </span>
              <span>
                <span className="cell cell-bad">·</span> Half or more failed
              </span>
            </div>
            <h3 style={{ marginTop: 14 }}>What stands out</h3>
            {standouts(tasks, reports, configs).map((line) => (
              <p key={line} className="small">
                {line}
              </p>
            ))}
          </aside>
        </div>
      )}
    </main>
  );
}

/** A few plain observations: tasks that fail everywhere, and each config's worst task. */
function standouts(tasks: string[], reports: Report[], configs: string[]): string[] {
  const lines: string[] = [];
  const everywhere = tasks.filter((t) => reports.every((r) => r.tasks[t] && r.tasks[t].passed < r.tasks[t].attempts));
  if (everywhere.length && reports.length > 1) {
    lines.push(
      `${everywhere.join(", ")} ${everywhere.length === 1 ? "fails" : "fail"} in every config, so it's the task more than the setting.`,
    );
  }
  const solid = tasks.filter((t) => reports.every((r) => r.tasks[t] && r.tasks[t].passed === r.tasks[t].attempts));
  if (solid.length) lines.push(`${solid.length} of ${tasks.length} tasks pass every attempt in every config.`);
  const best = reports.reduce((b, r, i) => (r.summary.pass_rate > reports[b]!.summary.pass_rate ? i : b), 0);
  const worst = reports.reduce((w, r, i) => (r.summary.pass_rate < reports[w]!.summary.pass_rate ? i : w), 0);
  if (best !== worst) {
    const drops = tasks
      .map((t) => ({ t, drop: (reports[best]!.tasks[t]?.passed ?? 0) - (reports[worst]!.tasks[t]?.passed ?? 0) }))
      .sort((a, b) => b.drop - a.drop)[0];
    lines.push(
      `${configs[worst]} passes least (${pct(reports[worst]!.summary.pass_rate)}); against ${configs[best]} it loses most on ${drops?.t}.`,
    );
  }
  lines.push("A few attempts either way is often noise: compare two runs to see the intervals.");
  return lines;
}
