import { describe, expect, it } from "vitest";
import { buildTurns, type RawEvent } from "./events";
import { currentTodos, todosOf } from "./todos";

const todoCall = (id: string, todos: unknown): RawEvent[] => [
  { type: "tool_call_requested", call_id: id, name: "TodoWrite", args: { todos } },
];

describe("todos", () => {
  it("reads the list and treats unknown statuses as pending", () => {
    const call = { args: { todos: [{ content: "Run tests", status: "weird" }, { status: "completed" }, "x"] } };
    expect(todosOf(call)).toEqual([{ content: "Run tests", status: "pending" }]);
  });

  it("shows the last turn's latest list, skipping a rejected call", () => {
    const turns = buildTurns([
      { type: "turn_started", prompt: "Fix it" },
      ...todoCall("a", [{ content: "Read", status: "in_progress" }]),
      { type: "tool_result", call_id: "a", content: "saved" },
      ...todoCall("b", [{ content: "Read", status: "completed" }, { content: "Fix", status: "in_progress" }]),
      { type: "tool_result", call_id: "b", content: "saved" },
      ...todoCall("c", [{ content: "Bad", status: "in_progress" }, { content: "Worse", status: "in_progress" }]),
      { type: "tool_result", call_id: "c", content: "only one", is_error: true },
    ]);
    expect(currentTodos(turns)?.map((t) => t.content)).toEqual(["Read", "Fix"]);
  });

  it("has no list when the last turn made none", () => {
    const turns = buildTurns([
      { type: "turn_started", prompt: "One" },
      ...todoCall("a", [{ content: "Read", status: "completed" }]),
      { type: "turn_started", prompt: "Two" },
    ]);
    expect(currentTodos(turns)).toBeNull();
  });
});
