/**
 * Live preview: the dev servers a session has started, found in what its commands printed,
 * and when the files have changed, so a page open beside the conversation can reload.
 */
import type { ToolCall, Turn } from "./events";

const LOCAL = /\bhttps?:\/\/(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(?::\d{2,5})?(?:\/[^\s"'`<>)\]]*)?/gi;
// Tools whose results can hold a server's address.
const PRINTS = new Set(["Bash", "BashOutput", "Shell"]);
// Tools that change files without running a command.
const WRITES = new Set(["Write", "Edit", "MultiEdit", "Rename", "Delete", "Move", "ApplyPatch"]);

/** The local addresses in some output, in order, without repeats. 0.0.0.0 becomes localhost. */
export function localUrls(text: string): string[] {
  const found: string[] = [];
  for (const match of text.matchAll(LOCAL)) {
    const url = match[0].replace(/[.,;:!?]+$/, "").replace("//0.0.0.0", "//localhost");
    try {
      const href = new URL(url).href;
      if (!found.includes(href)) found.push(href);
    } catch {
      // not a URL after all
    }
  }
  return found;
}

function eachCall(turns: Turn[], visit: (call: ToolCall) => void) {
  const walk = (call: ToolCall) => {
    visit(call);
    call.subcalls.forEach(walk);
  };
  for (const turn of turns) for (const item of turn.items) if (item.kind === "tool") walk(item.call);
}

/** The newest dev server address the session's commands printed, or null. */
export function latestServer(turns: Turn[]): string | null {
  let latest: string | null = null;
  eachCall(turns, (call) => {
    if (!PRINTS.has(call.name) || !call.result || call.result.isError) return;
    const urls = localUrls(call.result.content);
    if (urls.length) latest = urls[urls.length - 1] ?? latest;
  });
  return latest;
}

/**
 * A number that goes up each time a call that may have changed files finishes: the edit
 * tools, and commands, which can write too. A live page reloads when it changes.
 */
export function fileChanges(turns: Turn[]): number {
  let count = 0;
  eachCall(turns, (call) => {
    if (call.result && !call.result.isError && (WRITES.has(call.name) || PRINTS.has(call.name))) count += 1;
  });
  return count;
}
