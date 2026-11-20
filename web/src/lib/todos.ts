/**
 * The model's to-do list (the TodoWrite tool, src/zwans/tools/todo.py). Each call carries
 * the whole list, so the latest call is the current one.
 */

import type { ToolCall, Turn } from "./events";

export type TodoStatus = "pending" | "in_progress" | "completed";

export interface Todo {
  content: string;
  status: TodoStatus;
}

export const TODO_TOOL = "TodoWrite";

const STATUSES: TodoStatus[] = ["pending", "in_progress", "completed"];

export function todosOf(call: Pick<ToolCall, "args">): Todo[] {
  const list = call.args.todos;
  if (!Array.isArray(list)) return [];
  return list.flatMap((item): Todo[] => {
    if (!item || typeof item !== "object") return [];
    const { content, status } = item as Record<string, unknown>;
    if (typeof content !== "string") return [];
    return [{ content, status: STATUSES.includes(status as TodoStatus) ? (status as TodoStatus) : "pending" }];
  });
}

/** The list from the last turn's latest accepted TodoWrite call, or null if it made none. */
export function currentTodos(turns: Turn[]): Todo[] | null {
  const turn = turns.at(-1);
  if (!turn) return null;
  for (let i = turn.items.length - 1; i >= 0; i--) {
    const item = turn.items[i]!;
    if (item.kind === "tool" && item.call.name === TODO_TOOL && !item.call.result?.isError) {
      return todosOf(item.call);
    }
  }
  return null;
}
