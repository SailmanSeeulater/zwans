/**
 * Slash commands typed in a session's message box: /loop works until a check passes,
 * /budget shows or sets the spending cap, /plan and /go plan first and then carry it out,
 * /compact summarizes the older messages now,
 * and commands from Markdown files in
 * .zwans/commands (the project's) or ~/.zwans/commands (yours) send their text.
 * Everything else goes to the model as typed.
 */
import type { CustomCommandInfo } from "./api";
import type { RawEvent } from "./events";

export interface SlashCommand {
  name: string;
  args: string;
  about: string;
  example: string;
  /** Where a command from a file came from; none for Zwans's own. */
  scope?: "project" | "user";
  /** A file's command that loops until this passes. */
  check?: string;
}

/** Commands from files, in the shape the menu shows. */
export function fromFiles(commands: CustomCommandInfo[] | undefined): SlashCommand[] {
  return (commands ?? []).map((c) => ({
    name: c.name,
    args: c.args,
    about: c.description,
    example: `/${c.name}`,
    scope: c.scope,
    check: c.check || undefined,
  }));
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
  {
    name: "plan",
    args: "[task | off]",
    about: "Plan first: Zwans looks and proposes, and nothing changes until /go",
    example: "/plan add a cache to the API",
  },
  {
    name: "go",
    args: "",
    about: "Carry out the plan: plan mode goes off",
    example: "/go",
  },
  {
    name: "compact",
    args: "",
    about: "Summarize the older messages now, to free up context",
    example: "/compact",
  },
];

export type Parsed =
  | { name: "loop" | "budget" | "plan" | "go" | "compact"; argument: string }
  | { name: "custom"; command: string; argument: string }
  | { name: "unknown"; typed: string };

/**
 * The command a message is, or null when it's a message for the model. As in the terminal,
 * a command is "/" and a name as the first word; "/etc/hosts is wrong" has a second slash,
 * so it's a message.
 */
export function parseCommand(text: string, custom: SlashCommand[] = []): Parsed | null {
  const trimmed = text.trim();
  const first = trimmed.split(/\s+/, 1)[0] ?? "";
  if (!/^\/[a-z][a-z0-9-]*$/i.test(first)) return null;
  const name = first.slice(1).toLowerCase();
  const argument = trimmed.slice(first.length).trim();
  if (name === "loop" || name === "budget" || name === "plan" || name === "go" || name === "compact") {
    return { name, argument };
  }
  if (custom.some((c) => c.name === name)) return { name: "custom", command: name, argument };
  return { name: "unknown", typed: first };
}

/** The commands to offer while a "/" and the start of a name are being typed: Zwans's own
 * first, then the project's and yours. */
export function matching(draft: string, custom: SlashCommand[] = []): SlashCommand[] {
  if (!/^\/[a-z0-9-]*$/i.test(draft)) return [];
  const typed = draft.slice(1).toLowerCase();
  return [...COMMANDS, ...custom].filter((c) => c.name.startsWith(typed));
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
