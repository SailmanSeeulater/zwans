import { describe, expect, it } from "vitest";
import type { SessionStatus } from "./api";
import { alerts, snapshot } from "./notify";

const status = (id: string, running: boolean, waiting: string[] = [], title = `Task ${id}`) =>
  ({ type: "status", id, title, running, waiting_for: waiting }) as unknown as SessionStatus;
const both = { done: true, waiting: true };

describe("alerts", () => {
  it("says when a turn finishes", () => {
    const before = snapshot([status("a", true)]);
    expect(alerts(before, [status("a", false)], both)).toEqual([{ id: "a", kind: "done", title: "Task a", body: "Finished." }]);
  });

  it("says when something new waits for you, and which kind", () => {
    const before = snapshot([status("a", true), status("b", true)]);
    const now = [status("a", true, ["call-1"]), status("b", true, ["question"])];
    expect(alerts(before, now, both).map((a) => [a.id, a.kind, a.body])).toEqual([
      ["a", "waiting", "Zwans needs your OK to go on."],
      ["b", "waiting", "Zwans has a question for you."],
    ]);
  });

  it("says nothing for sessions it hadn't seen, or that didn't change", () => {
    expect(alerts(new Map(), [status("a", false)], both)).toEqual([]);
    const before = snapshot([status("a", true, ["c1"])]);
    expect(alerts(before, [status("a", true, ["c1"])], both)).toEqual([]);
  });

  it("leaves out what's turned off", () => {
    const before = snapshot([status("a", true), status("b", true)]);
    const now = [status("a", false), status("b", true, ["c1"])];
    expect(alerts(before, now, { done: false, waiting: true }).map((a) => a.kind)).toEqual(["waiting"]);
    expect(alerts(before, now, { done: true, waiting: false }).map((a) => a.kind)).toEqual(["done"]);
  });
});
