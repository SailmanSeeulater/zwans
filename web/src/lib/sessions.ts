import type { SavedSession, SessionList, SessionStatus } from "./api";

/** The sidebar's sessions: pinned ones first, then the open ones, then the latest few. While
 * something is typed in its search box, only `found` is shown: every saved session that matches. */
export interface Arranged {
  pinned: SavedSession[];
  open: SessionStatus[];
  recent: SavedSession[];
  found: SavedSession[] | null;
}

export function arrange(list: SessionList | null | undefined, query: string, recentCount: number): Arranged {
  const saved = list?.saved ?? [];
  const pinned = saved.filter((s) => s.pinned);
  const pins = new Set(pinned.map((s) => s.id));
  return {
    pinned,
    open: (list?.live ?? []).filter((s) => !pins.has(s.id)),
    recent: saved.filter((s) => !s.live && !s.pinned).slice(0, recentCount),
    found: words(query).length ? saved.filter((s) => matches(s, query)) : null,
  };
}

/** Whether every word typed is in the session's title, its folder or its model, in any case. */
export function matches(session: Pick<SavedSession, "title" | "workspace" | "model" | "chat">, query: string): boolean {
  const text = `${session.title} ${session.chat ? "chat" : session.workspace} ${session.model}`.toLowerCase();
  return words(query).every((w) => text.includes(w));
}

function words(query: string): string[] {
  return query.toLowerCase().split(/\s+/).filter(Boolean);
}
