/**
 * What a model call's request held, piece by piece: each turn's messages and each tool
 * result, as far as the event stream shows them.
 *
 * The API counts only totals, and the model_call event splits that total four ways (system,
 * tools, messages, tool results). Within a part, the pieces here share its tokens in
 * proportion to their length in characters, so they are estimates; the four parts are not.
 */

import type { RawEvent } from "./events";
import type { ContextSplit } from "./calls";

export interface Piece {
  part: "messages" | "tool_results";
  label: string;
  chars: number;
  /** Added since the previous call of the main loop, so not read from the cache yet. */
  fresh: boolean;
}

const str = (value: unknown): string => (typeof value === "string" ? value : "");

function keyArg(args: Record<string, unknown>): string {
  for (const key of ["path", "command", "pattern", "query", "url", "description", "name"]) {
    const value = args[key];
    if (typeof value === "string" && value) return value.split("\n")[0]!.slice(0, 40);
  }
  return "";
}

/**
 * The pieces in the request of main-loop call number `callIndex` (0-based, counting only
 * the main loop's turn calls).
 */
export function piecesAt(events: RawEvent[], callIndex: number): Piece[] {
  let pieces: Piece[] = [];
  let seenAtLastCall = 0;
  let turn = 0;
  let mainCalls = 0;
  let turnText: Piece | null = null;
  const names = new Map<string, string>();

  for (const event of events) {
    switch (event.type) {
      case "turn_started":
        turn += 1;
        turnText = { part: "messages", label: `Turn ${turn}`, chars: str(event.prompt).length, fresh: false };
        pieces.push(turnText);
        break;
      case "text_delta":
      case "thinking_delta":
        if (turnText) turnText.chars += str(event.text).length;
        break;
      case "tool_call_requested": {
        const args = (event.args ?? {}) as Record<string, unknown>;
        names.set(str(event.call_id), `${str(event.name)} ${keyArg(args)}`.trim());
        if (turnText) turnText.chars += JSON.stringify(args).length;
        break;
      }
      case "tool_result":
        pieces.push({
          part: "tool_results",
          label: names.get(str(event.call_id)) ?? "Tool result",
          chars: str(event.content).length,
          fresh: false,
        });
        break;
      case "context_compacted": {
        // The older messages became one summary; this turn's prompt stays (roughly what's kept).
        const kept = turnText ? [turnText] : [];
        pieces = [
          { part: "messages", label: "Summary of earlier turns", chars: str(event.summary).length, fresh: false },
          ...kept,
        ];
        seenAtLastCall = 0;
        break;
      }
      case "model_call":
        if (event.purpose === "summary") break;
        if (mainCalls === callIndex) {
          // The current turn's messages grow with every call, so they're never all cached.
          return pieces.map((piece, i) => ({ ...piece, fresh: i >= seenAtLastCall || piece === turnText }));
        }
        mainCalls += 1;
        seenAtLastCall = pieces.length;
        break;
    }
  }
  return pieces;
}

export interface Tile {
  id: string;
  part: keyof ContextSplit;
  label: string;
  value: number;
  fresh: boolean;
}

/** The tiles for a call: the four parts, the two big ones split into pieces. Pieces under
 * `minShare` of their part are merged, so every tile is big enough to read. */
export function tilesFor(split: ContextSplit, pieces: Piece[], minShare = 0.06): Tile[] {
  const tiles: Tile[] = [
    { id: "system", part: "system", label: "System prompt", value: split.system, fresh: false },
    { id: "tools", part: "tools", label: "Tool definitions", value: split.tools, fresh: false },
  ];
  for (const part of ["messages", "tool_results"] as const) {
    const own = pieces.filter((p) => p.part === part && p.chars > 0);
    const chars = own.reduce((sum, p) => sum + p.chars, 0);
    if (!split[part]) continue;
    if (!chars) {
      tiles.push({ id: part, part, label: part === "messages" ? "Messages" : "Tool results", value: split[part], fresh: false });
      continue;
    }
    let other = 0;
    let otherCount = 0;
    let otherFresh = false;
    own.forEach((piece, i) => {
      const share = piece.chars / chars;
      if (share < minShare) {
        other += share;
        otherCount += 1;
        otherFresh ||= piece.fresh;
      } else {
        tiles.push({ id: `${part}-${i}`, part, label: piece.label, value: share * split[part], fresh: piece.fresh });
      }
    });
    if (other > 0) {
      const label = otherCount === 1 ? "1 small piece" : `${otherCount} small pieces`;
      tiles.push({ id: `${part}-other`, part, label, value: other * split[part], fresh: otherFresh });
    }
  }
  return tiles;
}
