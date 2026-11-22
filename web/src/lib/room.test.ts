import { describe, expect, it } from "vitest";
import type { RoomLine, RoomStatus } from "./api";
import { applyRoomMessage, EMPTY, hueOf, mentionAt, nextAgentName, type RoomState } from "./room";

const status: RoomStatus = {
  type: "room",
  id: "r1",
  topic: "Tabs?",
  agents: [
    { name: "Ada", model: "m1", persona: "" },
    { name: "Bo", model: "m2", persona: "" },
  ],
  lines: [],
  dollars: 0,
  unpriced: [],
  budget: null,
  created_at: "",
  updated_at: "",
  running: false,
  speaking: null,
  next: "Ada",
};

const line = (speaker: string, text: string): RoomLine => ({ speaker, text, model: "m1", dollars: 0.01, cut: false });

describe("applyRoomMessage", () => {
  it("streams a reply, then turns it into a line", () => {
    let state: RoomState = applyRoomMessage(EMPTY, status);
    state = applyRoomMessage(state, { type: "speaker_started", speaker: "Ada", model: "m1" });
    state = applyRoomMessage(state, { type: "speaker_text", speaker: "Ada", text: "Tabs" });
    state = applyRoomMessage(state, { type: "speaker_text", speaker: "Ada", text: ", obviously." });
    expect(state.room?.speaking?.text).toBe("Tabs, obviously.");
    expect(state.room?.running).toBe(true);

    state = applyRoomMessage(state, { type: "line_added", line: line("Ada", "Tabs, obviously."), dollars: 0.01 });
    expect(state.room?.speaking).toBeNull();
    expect(state.room?.lines.map((l) => l.text)).toEqual(["Tabs, obviously."]);
    expect(state.room?.dollars).toBe(0.01);
  });

  it("says why a run stopped, except when its turns ran out", () => {
    const base = applyRoomMessage(EMPTY, status);
    expect(applyRoomMessage(base, { type: "room_stopped", reason: "turns", detail: "" }).stopped).toBeNull();
    expect(applyRoomMessage(base, { type: "room_stopped", reason: "budget", detail: "Spent it." }).stopped).toBe(
      "Spent it.",
    );
    expect(applyRoomMessage(base, { type: "room_stopped", reason: "stopped", detail: "" }).stopped).toBe("Stopped.");
  });

  it("takes the whole room again after a run, and keeps refusals", () => {
    let state = applyRoomMessage(EMPTY, status);
    state = applyRoomMessage(state, { type: "server_error", message: "Wait." });
    state = applyRoomMessage(state, { ...status, lines: [line("Ada", "Hi")] });
    expect(state.problem).toBe("Wait.");
    expect(state.room?.lines).toHaveLength(1);
  });
});

describe("room helpers", () => {
  it("gives each agent its own hue and the user none", () => {
    expect(hueOf(status.agents, "Ada")).not.toBe(hueOf(status.agents, "Bo"));
    expect(hueOf(status.agents, "User")).toBeNull();
  });

  it("names a new agent with the first free name", () => {
    expect(nextAgentName(["ada", "Bo"])).toBe("Cy");
  });

  it("completes an @mention being typed", () => {
    expect(mentionAt("what does @b", ["Ada", "Bo"])).toEqual(["Bo"]);
    expect(mentionAt("no mention", ["Ada"])).toEqual([]);
    expect(mentionAt("@Bo", ["Bo"])).toEqual([]);
  });
});
