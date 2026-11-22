import { describe, expect, it } from "vitest";
import { codeSpans, spent } from "./format";

describe("codeSpans", () => {
  it("marks the backticked parts as code", () => {
    expect(codeSpans("`ls -la` runs code")).toEqual([
      { text: "ls -la", code: true },
      { text: " runs code", code: false },
    ]);
    expect(codeSpans("Run `a` then `b`.")).toEqual([
      { text: "Run ", code: false },
      { text: "a", code: true },
      { text: " then ", code: false },
      { text: "b", code: true },
      { text: ".", code: false },
    ]);
  });

  it("leaves text alone when a backtick has no partner", () => {
    expect(codeSpans("a ` b")).toEqual([{ text: "a ` b", code: false }]);
    expect(codeSpans("plain")).toEqual([{ text: "plain", code: false }]);
  });
});

describe("spent", () => {
  it("doesn't round a small amount down to nothing", () => {
    expect(spent(0.0015)).toBe("<$0.01");
    expect(spent(0)).toBe("$0.00");
    expect(spent(6.04)).toBe("$6.04");
  });
});
