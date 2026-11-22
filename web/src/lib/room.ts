/** A room's state in the browser, kept from the messages its socket sends. */

import type { RoomMessage, RoomStatus } from "./api";

export const USER = "User";

export interface RoomState {
  room: RoomStatus | null;
  /** Why the last run stopped, when it's worth saying: the budget, an error, or a stop. */
  stopped: string | null;
  /** A request the server refused. */
  problem: string | null;
}

export const EMPTY: RoomState = { room: null, stopped: null, problem: null };

export function applyRoomMessage(state: RoomState, message: RoomMessage): RoomState {
  const room = state.room;
  switch (message.type) {
    case "room":
      return { ...state, room: message };
    case "server_error":
      return { ...state, problem: message.message };
    case "room_stopped":
      return { ...state, stopped: stopNote(message.reason, message.detail) };
    case "speaker_started":
      if (!room) return state;
      return {
        ...state,
        stopped: null,
        problem: null,
        room: { ...room, running: true, speaking: { speaker: message.speaker, model: message.model, text: "" } },
      };
    case "speaker_text":
      if (!room?.speaking) return state;
      return { ...state, room: { ...room, speaking: { ...room.speaking, text: room.speaking.text + message.text } } };
    case "line_added":
      if (!room) return state;
      return {
        ...state,
        problem: message.line.speaker === USER ? null : state.problem,
        room: {
          ...room,
          lines: [...room.lines, message.line],
          dollars: message.dollars,
          speaking: message.line.speaker === USER ? room.speaking : null,
        },
      };
  }
}

function stopNote(reason: string, detail: string): string | null {
  if (reason === "turns") return null;
  if (reason === "stopped") return "Stopped.";
  return detail || reason;
}

/** A hue for each agent, spread around the wheel in the room's order. The user has none. */
export function hueOf(agents: { name: string }[], name: string): number | null {
  const index = agents.findIndex((a) => a.name === name);
  if (index < 0) return null;
  return HUES[index % HUES.length] ?? 0;
}

const HUES = [210, 330, 140, 30, 270, 180, 0, 90];

/** An agent's name for the next one added: a short, distinct name not in use yet. */
export function nextAgentName(taken: string[]): string {
  const lower = new Set(taken.map((t) => t.toLowerCase()));
  return NAMES.find((n) => !lower.has(n.toLowerCase())) ?? `Agent${taken.length + 1}`;
}

const NAMES = ["Ada", "Bo", "Cy", "Dee", "Eli", "Fay", "Gus", "Hal"];

/** Who an @mention at the end of the draft could be, to complete it. */
export function mentionAt(draft: string, names: string[]): string[] {
  const match = /@([A-Za-z0-9_-]*)$/.exec(draft);
  if (!match) return [];
  const typed = (match[1] ?? "").toLowerCase();
  return names.filter((n) => n.toLowerCase().startsWith(typed) && n.toLowerCase() !== typed);
}
