"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import { buildTurns, type RawEvent } from "@/lib/events";
import { Conversation } from "./Conversation";
import { TokenMissing, useApi, useHasToken } from "./useApi";

export function TranscriptView() {
  const params = useSearchParams();
  const run = params.get("run") ?? "";
  const file = params.get("file") ?? "";
  const hasToken = useHasToken();
  const path = hasToken && run && file ? `/api/evals/${encodeURIComponent(run)}/transcripts/${encodeURIComponent(file)}` : null;
  const { data: events, error } = useApi<RawEvent[]>(path);
  const turns = useMemo(() => buildTurns(events ?? []), [events]);

  if (hasToken === false) {
    return (
      <main className="page">
        <TokenMissing />
      </main>
    );
  }
  return (
    <main className="page">
      <p>
        <Link href={`/evals/run/?name=${encodeURIComponent(run)}`}>← {run}</Link>
      </p>
      <h1>{file.replace(/\.jsonl$/, "")}</h1>
      {error && <div className="notice notice-bad">{error}</div>}
      {events && <Conversation turns={turns} />}
    </main>
  );
}
