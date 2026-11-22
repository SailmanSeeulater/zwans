"use client";

import { useMemo } from "react";
import { activity, contextShare, diffBlocks, diffStat, shortTokens, type Mark } from "@/lib/activity";
import { keyArgument, type Turn } from "@/lib/events";

const SOON = 0.85; // past this share of the way, compaction is near

/** How full the context is, up to where compaction starts. Opens the context inspector. */
export function ContextMeter({ tokens, compactAt, onOpen }: { tokens: number; compactAt: number; onOpen: () => void }) {
  const share = contextShare(tokens, compactAt);
  const soon = share >= SOON;
  const about = `Context: about ${shortTokens(tokens)} tokens of ${shortTokens(compactAt)}, where older turns get summarized`;
  return (
    <button className="context-meter" data-soon={soon || undefined} onClick={onOpen} title={about} aria-label={about}>
      <span className="context-meter-track" aria-hidden="true">
        <span className="context-meter-fill" style={{ width: `${Math.max(share * 100, share > 0 ? 3 : 0)}%` }} />
      </span>
      <span className="context-meter-text">{soon ? "compacts soon" : `${Math.round(share * 100)}%`}</span>
    </button>
  );
}

const KIND_WORDS = "Each mark is a tool call, top to bottom. Faint: reading. Accent: an edit. Grey: a command. Green: tests passed. Red: failed.";

/** A narrow strip beside the conversation with one mark per tool call, by turn. A mark jumps
 * to its call's card. Shown once there are a few calls to see. */
export function ActivityStrip({ turns }: { turns: Turn[] }) {
  const marks = useMemo(() => activity(turns, keyArgument), [turns]);
  if (marks.length < 3) return null;
  return (
    <nav className="activity" aria-label="Tool calls in this session" title={KIND_WORDS}>
      {marks.map((mark, i) => (
        <button
          key={mark.id}
          className="activity-mark"
          data-kind={mark.kind}
          data-outcome={mark.outcome ?? undefined}
          data-new-turn={(i > 0 && marks[i - 1]?.turn !== mark.turn) || undefined}
          title={mark.label}
          aria-label={mark.label}
          onClick={() => jumpTo(mark)}
        />
      ))}
    </nav>
  );
}

function jumpTo(mark: Mark) {
  const card = document.getElementById(`call-${mark.id}`);
  if (!card) return;
  card.scrollIntoView({ block: "center", behavior: "smooth" });
  card.classList.remove("tool-flash");
  void card.getBoundingClientRect(); // restarts the flash when the same card is picked twice
  card.classList.add("tool-flash");
}

/** "+12 −3" and five blocks, for an edit's card. */
export function DiffCount({ diff }: { diff: string }) {
  const { added, removed } = diffStat(diff);
  if (added + removed === 0) return null;
  const about = `${added} line${added === 1 ? "" : "s"} added, ${removed} removed`;
  return (
    <span className="diff-count" title={about} aria-label={about}>
      <span className="diff-count-add">+{added}</span>
      <span className="diff-count-del">−{removed}</span>
      <span className="diff-blocks" aria-hidden="true">
        {diffBlocks(added, removed).map((block, i) => (
          <span key={i} data-block={block} />
        ))}
      </span>
    </span>
  );
}
