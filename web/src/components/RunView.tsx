"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { Report } from "@/lib/api";
import { pct, plural, spent } from "@/lib/format";
import { TokenMissing, useApi, useHasToken } from "./useApi";

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
      <Link href="/evals/" className="back-link">
        <ChevronLeft size={14} aria-hidden="true" /> Eval runs
      </Link>
      <h1>{name}</h1>
      {error && <div className="notice notice-bad">{error}</div>}
      {!report && !error && <p className="muted">Loading…</p>}
      {report && (
        <>
          <p className="muted">
            {report.agent} · {report.model} · effort {report.effort} · config {report.config.name} · {report.executor} ·
            started {report.started_at.replace("T", " ").slice(0, 16)} · {plural(report.repeats, "attempt")} per task
            {report.out_of_budget && " · stopped when the budget ran out"}
          </p>
          <p>
            <strong>
              {report.summary.passed}/{report.summary.attempts} passed ({pct(report.summary.pass_rate)})
            </strong>{" "}
            · {spent(report.summary.dollars)} · {report.summary.mean_model_calls.toFixed(1)} model calls and{" "}
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
                        aria-label={`Transcript of ${attempt.task}, attempt ${attempt.repeat}`}
                      >
                        Open
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
