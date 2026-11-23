import { describe, expect, it } from "vitest";
import { budgetLevel, fromFiles, loopState, matching, parseCommand } from "./commands";

describe("parseCommand", () => {
  it("reads /loop and /budget, and leaves paths and plain messages to the model", () => {
    expect(parseCommand("/loop until pytest -q")).toEqual({ name: "loop", argument: "until pytest -q" });
    expect(parseCommand("  /budget $2 ")).toEqual({ name: "budget", argument: "$2" });
    expect(parseCommand("/budget")).toEqual({ name: "budget", argument: "" });
    expect(parseCommand("/frobnicate")).toEqual({ name: "unknown", typed: "/frobnicate" });
    expect(parseCommand("/etc/hosts is wrong")).toBeNull();
    expect(parseCommand("fix /loop handling")).toBeNull();
  });

  it("offers the commands that start with what's typed", () => {
    expect(matching("/").map((c) => c.name)).toEqual(["loop", "budget"]);
    expect(matching("/bu").map((c) => c.name)).toEqual(["budget"]);
    expect(matching("/loop until")).toEqual([]);
    expect(matching("hello")).toEqual([]);
  });
});

describe("loopState", () => {
  it("follows the latest loop's checks to its end", () => {
    const events = [
      { type: "loop_checked", check: "pytest", round: 0, rounds: 5, passed: false },
      { type: "turn_started", prompt: "x" },
      { type: "loop_checked", check: "pytest", round: 1, rounds: 5, passed: false },
    ];
    expect(loopState(events)).toEqual({ check: "pytest", round: 1, rounds: 5, active: true, lastFailed: true });
    expect(loopState([...events, { type: "loop_ended", reason: "rounds" }])?.active).toBe(false);
    expect(loopState([])).toBeNull();
  });
});

it("says how close a session is to its budget", () => {
  expect([budgetLevel(0.5, 2), budgetLevel(1.7, 2), budgetLevel(2, 2)]).toEqual(["ok", "near", "spent"]);
});

describe("commands from files", () => {
  const custom = fromFiles([
    { name: "fix-lint", description: "Fix the lint", args: "[path]", scope: "project", check: "ruff check ." },
    { name: "explain", description: "Explain it", args: "", scope: "user", check: "" },
  ]);

  it("are commands only once a file defines them", () => {
    expect(parseCommand("/fix-lint src", custom)).toEqual({ name: "custom", command: "fix-lint", argument: "src" });
    expect(parseCommand("/explain", custom)).toEqual({ name: "custom", command: "explain", argument: "" });
    expect(parseCommand("/explain")).toEqual({ name: "unknown", typed: "/explain" });
    expect(parseCommand("/loop until x", custom)).toEqual({ name: "loop", argument: "until x" });
  });

  it("show in the menu after Zwans's own, with where they came from", () => {
    expect(matching("/", custom).map((c) => c.name)).toEqual(["loop", "budget", "fix-lint", "explain"]);
    expect(matching("/fi", custom)).toMatchObject([{ name: "fix-lint", scope: "project", check: "ruff check ." }]);
    expect(matching("/ex", custom)[0]?.check).toBeUndefined();
  });
});
