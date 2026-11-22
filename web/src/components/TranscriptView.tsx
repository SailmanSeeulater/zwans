"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import type { Report } from "@/lib/api";
import { buildTurns, type RawEvent } from "@/lib/events";
import { dollars, plural, seconds } from "@/lib/format";
import { Conversation } from "./Conversation";
import { TokenMissing, useApi, useHasToken } from "./useApi";

/** One eval attempt: how it ended, what its check said if it failed, and the conversation. */
export function TranscriptView() {
  const params = useSearchParams();
  const run = params.get("run") ?? "";
  const file = params.get("file") ?? "";
  const hasToken = useHasToken();
  const ready = hasToken && run && file;
  const path = ready ? `/api/evals/${encodeURIComponent(run)}/transcripts/${encodeURIComponent(file)}` : null;
  const { data: events, error } = useApi<RawEvent[]>(path);
  const { data: report } = useApi<Report>(ready ? `/api/evals/${encodeURIComponent(run)}` : null);
  const turns = useMemo(() => buildTurns(events ?? []), [events]);
  const attempt = report?.attempts.find((a) => a.transcript === file);

  if (hasToken === false) {
    return (
      <main className="page">
        <TokenMissing />
      </main>
    );
  }
  return (
    <main className="page">
      <Link href={`/evals/run/?name=${encodeURIComponent(run)}`} className="back-link">
        <ChevronLeft size={14} aria-hidden="true" /> {run}
      </Link>
      <h1>{attempt ? `${attempt.task}, attempt ${attempt.repeat}` : file.replace(/\.jsonl$/, "")}</h1>
      {attempt && (
        <p className="muted">
          <span className={`status-${attempt.status}`}>{attempt.status}</span> · stopped on {attempt.stop_reason} ·{" "}
          {dollars(attempt.dollars)} · {plural(attempt.model_calls, "model call")} · {seconds(attempt.seconds)}
        </p>
      )}
      {attempt && attempt.status !== "passed" && attempt.check_output && (
        <details className="compacted">
          <summary>
            Why it failed: the check&apos;s output
            {attempt.check_exit !== null ? ` (exit code ${attempt.check_exit})` : ""}
          </summary>
          <pre>{attempt.check_output}</pre>
        </details>
      )}
      {error && <div className="notice notice-bad">{error}</div>}
      {!events && !error && <p className="muted">Loading…</p>}
      {events && <Conversation turns={turns} />}
    </main>
  );
}
