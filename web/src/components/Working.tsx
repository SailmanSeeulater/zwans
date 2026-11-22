"use client";

import { useEffect, useState, type ReactNode } from "react";
import { tokens } from "@/lib/format";
import { elapsed, type Liveness, type Phase } from "@/lib/working";

/** Zwans's mark while it works: eight rays that light up in turn. Still, it's a small star. */
export function Spark({ size = 14, still = false }: { size?: number; still?: boolean }) {
  return (
    <svg className="spark" data-still={still || undefined} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      {Array.from({ length: 8 }, (_, i) => (
        <line
          key={i}
          x1="12"
          y1="2.5"
          x2="12"
          y2="8"
          transform={`rotate(${i * 45} 12 12)`}
          style={{ animationDelay: `${i * 0.11}s` }}
        />
      ))}
    </svg>
  );
}

/** The line under the conversation while a turn runs: what it's doing, on what, for how
 * long, and what the turn has written so far. */
export function WorkingLine({ phase, startedAt, outputTokens }: { phase: Phase; startedAt: number | null; outputTokens: number }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const seconds = startedAt === null ? null : (now - startedAt) / 1000;
  return (
    <div className="working" role="status" aria-live="polite" aria-label={`${phase.verb} ${phase.detail}`.trim()}>
      <Spark />
      {/* Keyed by the verb, so a new phase slides in. */}
      <span key={phase.verb} className="working-verb shimmer">
        {phase.verb}
      </span>
      {phase.detail && (
        <span className="working-detail" title={phase.detail}>
          {phase.detail}
        </span>
      )}
      <span className="working-meta">
        {seconds !== null && seconds >= 1 && <span>{elapsed(seconds)}</span>}
        {outputTokens > 0 && <span title="Tokens the model has written this turn">↓ {tokens(outputTokens)}</span>}
      </span>
    </div>
  );
}

const DOT_WORDS: Record<Liveness, string> = { working: "Working", waiting: "Waiting for you", idle: "Idle" };

/** A session's state as a dot: it breathes while working, holds a ring while it waits for
 * you, and is hollow when idle. */
export function StatusDot({ state }: { state: Liveness }) {
  return <span className="status-dot" data-state={state} role="img" aria-label={DOT_WORDS[state]} title={DOT_WORDS[state]} />;
}

/** Wraps something that appears while the session is live, so it eases in. What was already
 * there when the page loaded doesn't move. */
export function Enter({ live, children }: { live: boolean; children: ReactNode }) {
  const [fresh] = useState(live); // decided once, when it first appears
  return fresh ? <div className="enter">{children}</div> : <>{children}</>;
}
