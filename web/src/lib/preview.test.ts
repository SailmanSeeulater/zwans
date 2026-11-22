import { describe, expect, it } from "vitest";
import type { ToolCall, Turn } from "./events";
import { fileChanges, latestServer, localUrls } from "./preview";

const call = (name: string, content: string, isError = false): ToolCall => ({
  id: name + content.length,
  name,
  args: {},
  hooks: [],
  subcalls: [],
  result: { content, isError, untrusted: false, diff: null },
});

const turn = (...calls: ToolCall[]): Turn => ({
  prompt: "",
  number: 1,
  images: 0,
  items: calls.map((c) => ({ kind: "tool" as const, call: c })),
  modelCalls: 0,
  inputTokens: 0,
  outputTokens: 0,
});

describe("localUrls", () => {
  it("finds local addresses as dev servers print them", () => {
    const vite = "  ➜  Local:   http://localhost:5173/\n  ➜  Network: http://192.168.1.4:5173/";
    expect(localUrls(vite)).toEqual(["http://localhost:5173/"]);
    expect(localUrls("Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)")).toEqual([
      "http://localhost:8000/",
    ]);
    expect(localUrls("Serving at http://127.0.0.1:3000/docs.")).toEqual(["http://127.0.0.1:3000/docs"]);
    expect(localUrls("see https://example.com")).toEqual([]);
  });
});

describe("latestServer and fileChanges", () => {
  it("take the newest address a command printed, and count what may have changed files", () => {
    const turns = [
      turn(call("Bash", "ready on http://localhost:3000"), call("Read", "http://localhost:9999")),
      turn(call("Write", "Wrote a.html"), call("Bash", "http://localhost:4000 failed", true)),
    ];
    expect(latestServer(turns)).toBe("http://localhost:3000/");
    expect(fileChanges(turns)).toBe(2);
    expect(latestServer([])).toBeNull();
  });
});
