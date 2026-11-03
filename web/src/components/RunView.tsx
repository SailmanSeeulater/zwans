"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { Report } from "@/lib/api";
import { TokenMissing, useApi, useHasToken } from "./useApi";

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function RunView() {
  const name = useSearchParams().get("name") ?? "";
  const hasToken = useHasToken();
  const { data: report, error } = useApi<Report>(hasToken && name ? `/api/evals/${encodeURIComponent(name)}` : null);

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
      <h1>{name}</h1>
      {error && <div className="notice notice-bad">{error}</div>}
      {report && (
        <>
          <p className="muted">
            {report.agent} · {report.model} · effort {report.effort} · config {report.config.name} · {report.executor} ·
            started {report.started_at.replace("T", " ")} · ×{report.repeats}
            {report.out_of_budget && " · stopped when the budget ran out"}
          </p>
          <p>
            <strong>
              {report.summary.passed}/{report.summary.attempts} passed ({pct(report.summary.pass_rate)})
            </strong>{" "}
            · ${report.summary.dollars.toFixed(2)} · {report.summary.mean_model_calls.toFixed(1)} model calls and{" "}
            {report.summary.mean_tool_calls.toFixed(1)} tool calls per attempt
          </p>

          <h2>Attempts</h2>
          <table className="table">
            <thead>
              <tr>
                <th>Task</th>
                <th>Result</th>
                <th>Stopped</th>
                <th className="num">Spent</th>
                <th className="num">Model calls</th>
                <th className="num">Tool calls</th>
                <th className="num">Seconds</th>
                <th>Transcript</th>
              </tr>
            </thead>
            <tbody>
              {report.attempts.map((attempt) => (
                <tr key={`${attempt.task}-${attempt.repeat}`}>
                  <td>
                    {attempt.task} <span className="muted">#{attempt.repeat}</span>
                    {attempt.errors.length > 0 && (
                      <div className="muted" style={{ fontSize: 13 }}>
                        {attempt.errors[0]}
                      </div>
                    )}
                  </td>
                  <td className={`status-${attempt.status}`}>{attempt.status}</td>
                  <td>{attempt.stop_reason}</td>
                  <td className="num">${attempt.dollars.toFixed(4)}</td>
                  <td className="num">{attempt.model_calls}</td>
                  <td className="num">{attempt.tool_calls}</td>
                  <td className="num">{attempt.seconds.toFixed(0)}</td>
                  <td>
                    {attempt.transcript && (
                      <Link
                        href={`/evals/transcript/?run=${encodeURIComponent(name)}&file=${encodeURIComponent(attempt.transcript)}`}
                      >
                        view
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </main>
  );
}
