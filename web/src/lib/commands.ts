/**
 * Slash commands typed in a session's message box: /loop works until a check passes, and
 * /budget shows or sets the spending cap. Everything else goes to the model as typed.
 */
import type { RawEvent } from "./events";

export interface SlashCommand {
  name: string;
  args: string;
  about: string;
  example: string;
}

export const COMMANDS: SlashCommand[] = [
  {
    name: "loop",
    args: "[rounds] until <check> [task]",
    about: "Keep working until a check passes, sending the model what fails",
    example: "/loop until pytest -q",
  },
  {
    name: "budget",
    args: "[dollars | off]",
    about: "Show the spending cap, or set one; turns stop when it's spent",
    example: "/budget 2",
  },
];

export type Parsed = { name: "loop" | "budget"; argument: string } | { name: "unknown"; typed: string };

/**
 * The command a message is, or null when it's a message for the model. As in the terminal,
 * a command is "/" and a name as the first word; "/etc/hosts is wrong" has a second slash,
 * so it's a message.
 */
export function parseCommand(text: string): Parsed | null {
  const trimmed = text.trim();
  const first = trimmed.split(/\s+/, 1)[0] ?? "";
  if (!/^\/[a-z][a-z-]*$/i.test(first)) return null;
  const name = first.slice(1).toLowerCase();
  const argument = trimmed.slice(first.length).trim();
  if (name === "loop" || name === "budget") return { name, argument };
  return { name: "unknown", typed: first };
}

/** The commands to offer while a "/" and the start of a name are being typed. */
export function matching(draft: string): SlashCommand[] {
  if (!/^\/[a-z-]*$/i.test(draft)) return [];
  const typed = draft.slice(1).toLowerCase();
  return COMMANDS.filter((c) => c.name.startsWith(typed));
}

export interface LoopState {
  check: string;
  round: number; // the turns done so far
  rounds: number;
  active: boolean;
  lastFailed: boolean;
}

/** Where the latest /loop stands, from the session's events; null when there's been none. */
export function loopState(events: RawEvent[]): LoopState | null {
  let state: LoopState | null = null;
  for (const event of events) {
    if (event.type === "loop_checked") {
      state = {
        check: String(event.check ?? ""),
        round: Number(event.round ?? 0),
        rounds: Number(event.rounds ?? 0),
        active: true,
        lastFailed: !event.passed,
      };
    } else if (event.type === "loop_ended" && state) {
      state = { ...(state as LoopState), active: false };
    }
  }
  return state;
}

/** How close a session is to its cap: under 80%, nearly there, or spent. */
export function budgetLevel(spent: number, cap: number): "ok" | "near" | "spent" {
  if (spent >= cap) return "spent";
  return spent >= cap * 0.8 ? "near" : "ok";
}
