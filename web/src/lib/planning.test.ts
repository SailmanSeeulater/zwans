import { describe, expect, it } from "vitest";
import { hasPlan } from "./planning";

describe("hasPlan", () => {
  const on = { type: "plan_mode", on: true };
  const ended = { type: "turn_ended", stop_reason: "end_turn" };

  it("is a plan once a turn has ended since plan mode went on", () => {
    expect(hasPlan([on], true)).toBe(false);
    expect(hasPlan([on, { type: "turn_started" }], true)).toBe(false);
    expect(hasPlan([on, ended], true)).toBe(true);
  });

  it("doesn't count turns from before plan mode, or anything while it's off", () => {
    expect(hasPlan([ended, on], true)).toBe(false);
    expect(hasPlan([on, ended], false)).toBe(false);
    expect(hasPlan([on, ended, { type: "plan_mode", on: false }, on], true)).toBe(false);
  });
});
