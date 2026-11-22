"use client";

import { ArrowUp, Plus, Square, StepForward, Users, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useEffect,
  useLayoutEffect,
  useReducer,
  useRef,
  useState,
} from "react";
import {
  api,
  roomSocket,
  type DemoInfo,
  type RoomAgent,
  type RoomLine,
  type RoomMessage,
  type RoomStatus,
  type SavedRoom,
} from "@/lib/api";
import { useIsMac } from "@/lib/platform";
import {
  applyRoomMessage,
  EMPTY,
  hueOf,
  mentionAt,
  nextAgentName,
  USER,
} from "@/lib/room";
import { Markdown } from "./Markdown";
import { ModelPicker } from "./ModelPicker";
import { TokenMissing, useApi, useHasToken } from "./useApi";

const RECONNECT_MS = 1_000;
const TURN_CHOICES = [1, 3, 6, 10];

/** /room/: set up a room of agents, or, with ?id=, watch one talk and join in. */
export function RoomView() {
  const id = useSearchParams().get("id");
  const hasToken = useHasToken();
  if (hasToken === false) {
    return (
      <main className="page">
        <h1>Rooms</h1>
        <TokenMissing />
      </main>
    );
  }
  if (hasToken === null) return null;
  return id ? <RoomChat key={id} id={id} /> : <RoomSetup />;
}

// -- setting one up

function RoomSetup() {
  const router = useRouter();
  const mac = useIsMac();
  const { data: demo } = useApi<DemoInfo>("/api/demo");
  const { data: rooms } = useApi<{ saved: SavedRoom[] }>("/api/rooms");
  const [topic, setTopic] = useState("");
  const [agents, setAgents] = useState<RoomAgent[]>([]);
  const [turns, setTurns] = useState(6);
  const [budget, setBudget] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // Two agents to start with, on the model a session would get, as soon as it's known.
  useEffect(() => {
    if (!demo || agents.length) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAgents([
      { name: "Ada", model: demo.model, persona: "" },
      { name: "Bo", model: demo.model, persona: "" },
    ]);
  }, [demo, agents.length]);

  const change = (index: number, patch: Partial<RoomAgent>) =>
    setAgents((all) =>
      all.map((a, i) => (i === index ? { ...a, ...patch } : a)),
    );

  const ready =
    topic.trim() &&
    agents.length > 0 &&
    agents.every((a) => a.name.trim() && a.model.trim());

  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setProblem(null);
    try {
      const room = await api<RoomStatus>("/api/rooms", {
        method: "POST",
        body: JSON.stringify({
          topic,
          agents: agents.map((a) => ({
            ...a,
            name: a.name.trim(),
            persona: a.persona.trim(),
          })),
          turns,
          budget: budget.trim() ? Number(budget) : null,
        }),
      });
      router.push(`/room/?id=${encodeURIComponent(room.id)}`);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const open = async (roomId: string) => {
    try {
      await api<RoomStatus>(`/api/rooms/${encodeURIComponent(roomId)}/open`, {
        method: "POST",
      });
      router.push(`/room/?id=${encodeURIComponent(roomId)}`);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <main className="page home">
      <form className="panel glass home-start" onSubmit={start}>
        <h1>Open a room</h1>
        <p className="muted" style={{ margin: 0 }}>
          Agents on different models talk it over, one at a time. Mention one as{" "}
          <code>@Name</code> to choose who answers. Rooms have no tools: the
          agents only talk.
        </p>
        <textarea
          className="textarea home-task"
          placeholder="What should they talk about? As: Should a small team use a monorepo?"
          aria-label="Topic"
          value={topic}
          rows={2}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start(e);
          }}
        />
        <div className="room-agents">
          {agents.map((agent, index) => (
            <div
              key={index}
              className="room-agent-row"
              style={
                {
                  "--hue": hueOf(agents, agent.name) ?? 0,
                } as React.CSSProperties
              }
            >
              <span className="room-dot" aria-hidden="true" />
              <input
                className="input room-agent-name"
                aria-label={`Agent ${index + 1}'s name`}
                value={agent.name}
                maxLength={24}
                onChange={(e) =>
                  change(index, {
                    name: e.target.value.replace(/[^A-Za-z0-9_-]/g, ""),
                  })
                }
              />
              <ModelPicker
                model={agent.model || "choose a model"}
                onChoose={(model) => change(index, { model })}
                onError={setProblem}
              />
              <input
                className="input room-agent-persona"
                placeholder="Who they are (optional), as a skeptical security reviewer"
                aria-label={`Who ${agent.name || "this agent"} is`}
                value={agent.persona}
                onChange={(e) => change(index, { persona: e.target.value })}
              />
              <button
                type="button"
                className="button button-quiet icon-button"
                aria-label={`Remove ${agent.name || "this agent"}`}
                title="Remove"
                disabled={agents.length <= 1}
                onClick={() =>
                  setAgents((all) => all.filter((_, i) => i !== index))
                }
              >
                <X size={14} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
        <div className="row">
          <button
            type="button"
            className="button button-quiet"
            disabled={agents.length >= 8}
            onClick={() =>
              setAgents((all) => [
                ...all,
                {
                  name: nextAgentName(all.map((a) => a.name)),
                  model: all.at(-1)?.model ?? demo?.model ?? "",
                  persona: "",
                },
              ])
            }
          >
            <Plus size={14} aria-hidden="true" />
            Add an agent
          </button>
          <span style={{ flex: 1 }} />
          <label className="muted small room-field">
            Turns
            <select
              className="input"
              value={turns}
              onChange={(e) => setTurns(Number(e.target.value))}
            >
              {TURN_CHOICES.map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <label className="muted small room-field">
            Budget $
            <input
              className="input"
              inputMode="decimal"
              placeholder="none"
              value={budget}
              onChange={(e) =>
                setBudget(e.target.value.replace(/[^0-9.]/g, ""))
              }
              style={{ width: 64 }}
            />
          </label>
          <button className="button button-primary" disabled={busy || !ready}>
            {busy ? "Opening…" : "Open the room"}
          </button>
        </div>
        <p className="muted small" style={{ margin: 0 }}>
          Each turn sends the whole conversation to one agent&apos;s model.{" "}
          {mac ? "⌘↵" : "Ctrl+Enter"} opens it.
        </p>
      </form>
      {problem && <div className="notice notice-bad">{problem}</div>}

      <section className="panel glass">
        <h2 style={{ marginTop: 0 }}>Recent rooms</h2>
        {rooms && rooms.saved.length === 0 && (
          <p className="muted">None yet.</p>
        )}
        {rooms?.saved.map((room) => (
          <button
            key={room.id}
            className="folder-row"
            onClick={() => void open(room.id)}
            title="Open this room"
          >
            <span style={{ minWidth: 0, flex: 1, textAlign: "left" }}>
              <span className="room-recent-topic">{room.topic}</span>
              <span className="muted small">
                {room.agents.map((a) => a.name).join(", ")} · {room.lines}{" "}
                {room.lines === 1 ? "line" : "lines"} · $
                {room.dollars.toFixed(4)}
              </span>
            </span>
            <span className="muted small">
              {room.updated_at.replace("T", " ").slice(0, 16)}
            </span>
          </button>
        ))}
      </section>
    </main>
  );
}

// -- talking in one

function RoomChat({ id }: { id: string }) {
  const [state, dispatch] = useReducer(applyRoomMessage, EMPTY);
  const [connection, setConnection] = useState<
    "connecting" | "open" | "closed"
  >("connecting");
  const [closedWhy, setClosedWhy] = useState("");
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState(3);
  const socket = useRef<WebSocket | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);
  const reopened = useRef(false);

  useEffect(() => {
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ws: WebSocket;
    const connect = () => {
      ws = roomSocket(id);
      socket.current = ws;
      ws.onopen = () => setConnection("open");
      ws.onmessage = (message) =>
        dispatch(JSON.parse(String(message.data)) as RoomMessage);
      ws.onclose = (event) => {
        if (stopped) return;
        if (event.code === 4404 && !reopened.current) {
          // Saved, but not open in the server (it restarted): open it again, once.
          reopened.current = true;
          api<RoomStatus>(`/api/rooms/${encodeURIComponent(id)}/open`, {
            method: "POST",
          })
            .then(() => connect())
            .catch((err: unknown) => {
              setConnection("closed");
              setClosedWhy(err instanceof Error ? err.message : String(err));
            });
          return;
        }
        if (event.code === 4401 || event.code === 4404) {
          setConnection("closed");
          setClosedWhy(
            event.code === 4401
              ? "The server refused this browser's token. Open the link zwans serve printed."
              : "This room isn't open.",
          );
          return;
        }
        setConnection("connecting");
        retry = setTimeout(connect, RECONNECT_MS);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      ws.close();
    };
  }, [id]);

  const room = state.room;
  const running = room?.running ?? false;

  // Follow the conversation as it grows, unless the reader has scrolled up.
  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && pinned.current) box.scrollTop = box.scrollHeight;
  }, [room?.lines.length, room?.speaking?.text]);

  const send = (message: Record<string, unknown>) =>
    socket.current?.send(JSON.stringify(message));

  const say = () => {
    if (!draft.trim() || running) return;
    send({ type: "say", text: draft.trim(), turns });
    setDraft("");
  };

  const names = room?.agents.map((a) => a.name) ?? [];
  const suggestions = mentionAt(draft, names);

  return (
    <div className="session">
      <div className="session-main">
        <header className="session-head glass">
          <Users size={16} aria-hidden="true" style={{ flexShrink: 0 }} />
          <h1 title={room?.topic}>{room?.topic ?? "Room"}</h1>
          <span style={{ flex: 1 }} />
          {room && (
            <span
              className="pill pill-quiet"
              title={
                room.unpriced.length
                  ? `No price known for ${room.unpriced.join(", ")}`
                  : undefined
              }
            >
              ${room.dollars.toFixed(4)}
              {room.budget !== null && (
                <span className="muted"> of ${room.budget.toFixed(2)}</span>
              )}
              {room.unpriced.length > 0 && "+"}
            </span>
          )}
        </header>

        <div
          className="session-scroll"
          ref={scroller}
          onScroll={(e) => {
            const box = e.currentTarget;
            pinned.current =
              box.scrollHeight - box.scrollTop - box.clientHeight < 80;
          }}
        >
          <div className="session-column">
            {room && (
              <div className="room-roster">
                {room.agents.map((agent) => (
                  <span
                    key={agent.name}
                    className="pill pill-quiet room-chip"
                    style={
                      {
                        "--hue": hueOf(room.agents, agent.name) ?? 0,
                      } as React.CSSProperties
                    }
                    title={agent.persona || undefined}
                  >
                    <span className="room-dot" aria-hidden="true" />
                    {agent.name}
                    <span className="mono muted">{agent.model}</span>
                  </span>
                ))}
              </div>
            )}
            {room && room.lines.length === 0 && !room.speaking && (
              <p className="muted">
                Nobody has spoken yet. Run some turns, or say something to start
                them off. {room.next} goes first.
              </p>
            )}
            {room?.lines.map((line, index) => (
              <RoomLineView key={index} line={line} agents={room.agents} />
            ))}
            {room?.speaking && (
              <RoomLineView
                line={{
                  speaker: room.speaking.speaker,
                  model: room.speaking.model,
                  text: room.speaking.text,
                  dollars: null,
                  cut: false,
                }}
                agents={room.agents}
                live
              />
            )}
            {state.stopped && (
              <div className="notice notice-warn">{state.stopped}</div>
            )}
          </div>
        </div>

        <div className="composer glass">
          {connection === "closed" && (
            <div className="notice notice-bad">{closedWhy}</div>
          )}
          {state.problem && (
            <div className="notice notice-warn">{state.problem}</div>
          )}
          {suggestions.length > 0 && (
            <div className="row room-mentions">
              {suggestions.map((name) => (
                <button
                  key={name}
                  className="chip"
                  onClick={() =>
                    setDraft(draft.replace(/@[A-Za-z0-9_-]*$/, `@${name} `))
                  }
                >
                  @{name}
                </button>
              ))}
            </div>
          )}
          <textarea
            className="textarea"
            rows={2}
            placeholder={
              running
                ? "The agents are talking. Stop them to say something."
                : "Say something to the room. @Name picks who answers."
            }
            aria-label="Message to the room"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                say();
              }
            }}
            disabled={connection !== "open"}
          />
          <div className="composer-foot">
            <span className="muted small">
              {running
                ? `${room?.speaking?.speaker ?? "Someone"} is speaking…`
                : room
                  ? `Next: ${room.next}`
                  : "Connecting…"}
              {!running &&
                ` · Enter sends, then ${turns} ${turns === 1 ? "turn" : "turns"}`}
            </span>
            <span className="row">
              <label className="muted small room-field">
                Turns
                <select
                  className="input"
                  value={turns}
                  onChange={(e) => setTurns(Number(e.target.value))}
                >
                  {TURN_CHOICES.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              {running ? (
                <button
                  className="button button-danger"
                  onClick={() => send({ type: "stop" })}
                >
                  <Square size={14} aria-hidden="true" />
                  Stop
                </button>
              ) : (
                <>
                  <button
                    className="button"
                    onClick={() => send({ type: "continue", turns })}
                    disabled={connection !== "open"}
                    title={`Let the agents talk for ${turns} more ${turns === 1 ? "turn" : "turns"}`}
                  >
                    <StepForward size={14} aria-hidden="true" />
                    Continue
                  </button>
                  <button
                    className="button button-primary icon-button"
                    onClick={say}
                    disabled={connection !== "open" || !draft.trim()}
                    aria-label="Send"
                    title="Send"
                  >
                    <ArrowUp size={16} aria-hidden="true" />
                  </button>
                </>
              )}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function RoomLineView({
  line,
  agents,
  live = false,
}: {
  line: RoomLine;
  agents: RoomAgent[];
  live?: boolean;
}) {
  if (line.speaker === USER) {
    return (
      <div className="turn">
        <div className="prompt">{line.text}</div>
      </div>
    );
  }
  const hue = hueOf(agents, line.speaker) ?? 0;
  return (
    <div className={`room-line ${live ? "room-live" : ""}`} style={{ "--hue": hue } as React.CSSProperties}>
      <div className="room-speaker">
        <span className="room-dot" aria-hidden="true" />
        <span className="room-name">{line.speaker}</span>
        <span className="mono muted small">{line.model}</span>
        {line.dollars !== null && (
          <span className="muted small">${line.dollars.toFixed(4)}</span>
        )}
        {line.cut && <span className="pill pill-quiet">cut off</span>}
      </div>
      {line.text ? (
        <Markdown text={line.text} />
      ) : (
        <p className="muted small pulse">thinking…</p>
      )}
    </div>
  );
}
