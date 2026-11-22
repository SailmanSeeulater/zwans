import { describe, expect, it } from "vitest";
import type { SavedSession, SessionList, SessionStatus } from "./api";
import { arrange, matches } from "./sessions";

function saved(id: string, more: Partial<SavedSession> = {}): SavedSession {
  return {
    id,
    title: `Session ${id}`,
    named: false,
    pinned: false,
    workspace: `/Users/me/Dev/${id}`,
    model: "claude-haiku-5-5",
    turns: 1,
    updated_at: "2026-11-22T10:00:00",
    dollars: 0,
    live: false,
    ...more,
  };
}

const status = (id: string) => ({ type: "status", id, title: `Session ${id}` }) as unknown as SessionStatus;

describe("arrange", () => {
  const list: SessionList = {
    live: [status("a"), status("b")],
    saved: [saved("a", { live: true, pinned: true }), saved("c", { pinned: true }), saved("b", { live: true }), saved("d"), saved("e")],
  };

  it("puts pinned sessions first, open or not, and leaves them out of the other lists", () => {
    const shown = arrange(list, "", 6);
    expect(shown.pinned.map((s) => s.id)).toEqual(["a", "c"]);
    expect(shown.open.map((s) => s.id)).toEqual(["b"]);
    expect(shown.recent.map((s) => s.id)).toEqual(["d", "e"]);
    expect(shown.found).toBeNull();
  });

  it("keeps only the latest few as recent", () => {
    expect(arrange(list, "", 1).recent.map((s) => s.id)).toEqual(["d"]);
  });

  it("searches every saved session while something is typed", () => {
    expect(arrange(list, "  ", 6).found).toBeNull();
    expect(arrange(list, "session", 1).found?.map((s) => s.id)).toEqual(["a", "c", "b", "d", "e"]);
  });
});

describe("matches", () => {
  const session = saved("parser", { title: "Fix the CSV parser", model: "ollama/qwen3-coder:30b" });

  it("needs every word, in the title, folder or model, in any case", () => {
    expect(matches(session, "csv FIX")).toBe(true);
    expect(matches(session, "parser qwen3")).toBe(true);
    expect(matches(session, "csv tests")).toBe(false);
  });

  it("finds a chat by the word chat, not by its placeholder folder", () => {
    const chat = saved("x", { chat: true, workspace: "/Users/me/.zwans/chats/x" });
    expect(matches(chat, "chat")).toBe(true);
    expect(matches(chat, "zwans")).toBe(false);
  });
});
