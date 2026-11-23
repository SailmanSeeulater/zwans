"use client";

import { Check, ExternalLink, Flag, FolderOpen, Trophy } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  api,
  sessionSocket,
  type DemoInfo,
  type Mode,
  type RaceLane,
  type RaceStatus,
  type SessionList,
  type SessionStatus,
} from "@/lib/api";
import { buildTurns, type RawEvent } from "@/lib/events";
import { dollars, plural } from "@/lib/format";
import { modelName } from "@/lib/handoff";
import { useIsMac } from "@/lib/platform";
import { LETTERS, laneState, readBudget, shares, STATE_LABELS } from "@/lib/race";
import { usePrefs } from "@/lib/usePrefs";
import { Conversation, type Answer } from "./Conversation";
import { ModelPicker } from "./ModelPicker";
import { TokenMissing, useApi, useHasToken } from "./useApi";
import { Spark } from "./Working";

const RECONNECT_MS = 1_000;
const REFRESH_MS = 2_500;
const MODES: { id: Mode; label: string; about: string }[] = [
  { id: "read-only", label: "Read-only", about: "Reads and searches; changes nothing" },
  { id: "ask", label: "Ask", about: "Asks before each edit or command" },
  { id: "auto", label: "Auto", about: "Edits and local commands run without asking" },
];

/** /race/: give one task to two models, or, with ?id=, watch them side by side. */
export function RaceView() {
  const id = useSearchParams().get("id");
  const hasToken = useHasToken();
  if (hasToken === false) {
    return (
      <main className="page">
        <h1>Races</h1>
        <TokenMissing />
      </main>
    );
  }
  if (hasToken === null) return null;
  return id ? <RaceWatch key={id} id={id} /> : <RaceSetup />;
}

const messageOf = (error: unknown) => (error instanceof Error ? error.message : String(error));

// -- starting one

function RaceSetup() {
  const router = useRouter();
  const mac = useIsMac();
  const prefs = usePrefs();
  const { data: sessions } = useApi<SessionList>("/api/sessions");
  const { data: demo } = useApi<DemoInfo>("/api/demo");
  const { data: listed } = useApi<{ races: RaceStatus[] }>("/api/races");
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [chosenMode, setMode] = useState<Mode | null>(null);
  const mode: Mode = chosenMode ?? prefs.newMode;
  const [picked, setPicked] = useState<[string | null, string | null]>([null, null]);
  const [budget, setBudget] = useState("5");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const base = prefs.newModel || demo?.model || "claude-sonnet-5-5";
  const models: [string, string] = [
    picked[0] ?? base,
    picked[1] ?? (base === "claude-opus-5-5" ? "claude-sonnet-5-5" : "claude-opus-5-5"),
  ];
  const cap = readBudget(budget);
  const ready = Boolean(task.trim() && workspace.trim()) && !Number.isNaN(cap);

  const folders = useMemo(() => {
    const seen = new Set<string>();
    for (const s of sessions?.saved ?? []) {
      if (s.chat || s.workspace.includes("zwans-demo-") || s.workspace.includes("/races/")) continue;
      seen.add(s.workspace);
    }
    return [...seen].slice(0, 8);
  }, [sessions]);

  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    setBusy(true);
    setProblem(null);
    try {
      const race = await api<RaceStatus>("/api/races", {
        method: "POST",
        body: JSON.stringify({ workspace, prompt: task, models, mode, budget: cap }),
      });
      router.push(`/race/?id=${encodeURIComponent(race.id)}`);
    } catch (error) {
      setProblem(messageOf(error));
      setBusy(false);
    }
  };

  return (
    <main className="page">
      <form className="panel glass home-start race-start" onSubmit={start}>
        <h1>
          <Flag size={20} aria-hidden="true" /> Race two models
        </h1>
        <p className="muted">
          Both get the same task, each in its own copy of the folder, so neither touches your files. Watch them side by
          side, then keep the result you like.
        </p>
        <textarea
          className="textarea home-task"
          placeholder="The task, as you'd give it to one model."
          aria-label="Task"
          value={task}
          rows={3}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start(e);
          }}
        />
        <div className="row">
          <div className="folder-field">
            <FolderOpen size={15} aria-hidden="true" />
            <input
              className="mono"
              placeholder="/path/to/project"
              aria-label="Folder to race in"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              list="race-folders"
              required
            />
          </div>
          <div className="segmented" role="radiogroup" aria-label="Permission mode">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={mode === m.id}
                title={m.about}
                onClick={() => setMode(m.id)}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <div className="race-pick">
          {models.map((model, i) => (
            <div key={i} className="race-pick-lane" data-lane={i}>
              <span className="race-letter">{LETTERS[i]}</span>
              <ModelPicker
                model={model}
                onChoose={(name) => setPicked((p) => (i === 0 ? [name, p[1]] : [p[0], name]))}
                onError={setProblem}
              />
            </div>
          ))}
          <label className="race-budget" title="Both models' spending, added up. Leave it blank for no cap.">
            <span className="muted small">Budget between them</span>
            <span className="race-budget-field" data-bad={Number.isNaN(cap) || undefined}>
              $
              <input
                className="mono"
                inputMode="decimal"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
                placeholder="none"
                aria-label="Budget in dollars, between both models"
              />
            </span>
          </label>
          <button className="button button-primary" disabled={busy || !ready}>
            {busy ? "Copying…" : "Start the race"}
          </button>
        </div>
        <p className="muted small">
          {MODES.find((m) => m.id === mode)?.about}.{" "}
          {cap ? `Both stop once they've spent ${dollars(cap)} between them.` : "No cap on what they spend."}{" "}
          {mac ? "⌘↵" : "Ctrl+Enter"} starts.
        </p>
        <datalist id="race-folders">
          {folders.map((path) => (
            <option key={path} value={path} />
          ))}
        </datalist>
      </form>
      {problem && <div className="notice notice-bad">{problem}</div>}

      <section className="panel glass race-earlier">
        <h2 style={{ marginTop: 0 }}>Earlier races</h2>
        {!listed?.races.length && <p className="muted">None yet.</p>}
        {listed?.races.map((race) => (
          <Link key={race.id} href={`/race/?id=${encodeURIComponent(race.id)}`} className="race-row">
            <span className="race-row-prompt">{race.prompt.split("\n")[0]}</span>
            <span className="muted small mono">{race.lanes.map((lane) => lane.model).join(" vs ")}</span>
            <span className="muted small">{dollars(race.dollars)}</span>
            {race.kept && (
              <span className="race-kept-tag">
                <Check size={12} aria-hidden="true" /> kept {LETTERS[race.lanes.findIndex((l) => l.session_id === race.kept)]}
              </span>
            )}
          </Link>
        ))}
      </section>
    </main>
  );
}

// -- watching one

function RaceWatch({ id }: { id: string }) {
  const [race, setRace] = useState<RaceStatus | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [keeping, setKeeping] = useState<string | null>(null);
  const [kept, setKept] = useState<string | null>(null);
  // What each side's own socket says it has spent, ahead of the next refresh.
  const [live, setLive] = useState<Record<string, number>>({});

  const refresh = useCallback(async () => {
    try {
      setRace(await api<RaceStatus>(`/api/races/${encodeURIComponent(id)}`));
    } catch (error) {
      setProblem(messageOf(error));
    }
  }, [id]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
    const timer = setInterval(() => void refresh(), REFRESH_MS);
    return () => clearInterval(timer);
  }, [refresh]);

  const onSpent = useCallback((sessionId: string, spent: number) => {
    setLive((previous) => (previous[sessionId] === spent ? previous : { ...previous, [sessionId]: spent }));
  }, []);

  const keep = async (lane: RaceLane, letter: string) => {
    setKeeping(lane.session_id);
    setProblem(null);
    try {
      const result = await api<{ kept: { status: string; path: string }[] }>(
        `/api/races/${encodeURIComponent(id)}/keep`,
        { method: "POST", body: JSON.stringify({ session_id: lane.session_id }) },
      );
      setKept(`Kept ${letter}: ${plural(result.kept.length, "file")} copied into ${race?.workspace}.`);
      await refresh();
    } catch (error) {
      setProblem(messageOf(error));
    } finally {
      setKeeping(null);
    }
  };

  if (!race) {
    return <main className="page">{problem ? <div className="notice notice-bad">{problem}</div> : null}</main>;
  }
  const spent = race.lanes.map((lane) => Math.max(live[lane.session_id] ?? 0, lane.dollars));
  const total = spent.reduce((sum, n) => sum + n, 0);
  const parts = shares(spent, race.budget);
  const over = race.budget != null && total >= race.budget;

  return (
    <main className="page page-wide race-page">
      <header className="race-head">
        <div className="race-title">
          <Link href="/race/" className="muted small">
            ← Races
          </Link>
          <h1 title={race.prompt}>{race.prompt.split("\n")[0]}</h1>
          <span className="muted small mono">{race.workspace}</span>
        </div>
        <div className="race-money" data-over={over || undefined}>
          <div className="race-money-text">
            <strong>{dollars(total)}</strong>
            <span className="muted small">
              {race.budget != null ? ` of ${dollars(race.budget)} between them` : " between them, no cap"}
            </span>
          </div>
          <div className="race-money-bar" role="img" aria-label={`A spent ${dollars(spent[0])}, B spent ${dollars(spent[1])}`}>
            {parts.map((part, i) => (
              <span key={i} data-lane={i} style={{ width: `${part * 100}%` }} title={`${LETTERS[i]}: ${dollars(spent[i])}`} />
            ))}
          </div>
          <div className="race-money-legend small muted">
            {race.lanes.map((lane, i) => (
              <span key={lane.session_id} data-lane={i}>
                <i aria-hidden="true" /> {LETTERS[i]} {dollars(spent[i])}
              </span>
            ))}
          </div>
        </div>
      </header>
      {problem && <div className="notice notice-bad">{problem}</div>}
      {kept && (
        <div className="notice notice-good" role="status">
          <Trophy size={14} aria-hidden="true" /> {kept}
        </div>
      )}
      <div className="race-lanes">
        {race.lanes.map((lane, i) => (
          <LaneView
            key={lane.session_id}
            lane={lane}
            index={i}
            kept={race.kept}
            keeping={keeping}
            onKeep={() => void keep(lane, LETTERS[i] ?? "")}
            onSpent={onSpent}
          />
        ))}
      </div>
    </main>
  );
}

interface LaneProps {
  lane: RaceLane;
  index: number;
  kept: string;
  keeping: string | null;
  onKeep: () => void;
  onSpent: (sessionId: string, spent: number) => void;
}

function LaneView({ lane, index, kept, keeping, onKeep, onSpent }: LaneProps) {
  const id = lane.session_id;
  const [events, setEvents] = useState<RawEvent[]>([]);
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [animate, setAnimate] = useState(false);
  const socket = useRef<WebSocket | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true);

  useEffect(() => {
    let stopped = false;
    let reopened = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ws: WebSocket;
    const connect = () => {
      ws = sessionSocket(id);
      socket.current = ws;
      ws.onmessage = (message) => {
        const data = JSON.parse(String(message.data)) as RawEvent;
        if (data.type === "status") setStatus(data as unknown as SessionStatus);
        else if (data.type === "backlog") {
          setAnimate(false);
          setEvents((data.events as RawEvent[]) ?? []);
          requestAnimationFrame(() => requestAnimationFrame(() => setAnimate(true)));
        } else if (data.type !== "server_error") setEvents((previous) => [...previous, data]);
      };
      ws.onclose = (event) => {
        if (stopped || event.code === 4401) return;
        // After the server restarts, open the saved session again, once.
        if (event.code === 4404 && !reopened) {
          reopened = true;
          api(`/api/sessions/${encodeURIComponent(id)}/open`, { method: "POST" })
            .then(() => !stopped && connect())
            .catch(() => undefined);
          return;
        }
        if (event.code !== 4404) retry = setTimeout(connect, RECONNECT_MS);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(retry);
      ws.close();
    };
  }, [id]);

  useEffect(() => {
    if (status) onSpent(id, status.dollars);
  }, [id, status, onSpent]);

  const turns = useMemo(() => buildTurns(events), [events]);
  const running = status?.running ?? lane.running;
  const waiting = status ? status.waiting_for.length > 0 : lane.waiting;
  const state = laneState(running, waiting, events);
  const isKept = kept === id;

  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && pinned.current) box.scrollTop = box.scrollHeight;
  }, [events]);

  const answer = useCallback((callId: string, value: Answer) => {
    socket.current?.send(JSON.stringify({ type: "approve", call_id: callId, answer: value }));
  }, []);

  return (
    <section className="race-lane panel glass" data-lane={index} data-state={state} data-kept={isKept || undefined}>
      <header className="race-lane-head">
        <span className="race-letter">{LETTERS[index]}</span>
        <span className="race-lane-model" title={status?.model ?? lane.model}>
          {modelName(status?.model ?? lane.model)}
        </span>
        <span className="race-state" data-state={state}>
          {state === "working" ? <Spark size={12} /> : <i aria-hidden="true" />}
          {STATE_LABELS[state]}
        </span>
        <span className="race-lane-meta muted small">
          {dollars(Math.max(status?.dollars ?? 0, lane.dollars))}
        </span>
        <Link href={`/session/?id=${encodeURIComponent(id)}`} className="button button-quiet" title="Open it as a session">
          <ExternalLink size={13} aria-hidden="true" />
        </Link>
      </header>
      <div
        className="race-lane-body"
        ref={scroller}
        onScroll={(e) => {
          const box = e.currentTarget;
          pinned.current = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
        }}
      >
        <Conversation turns={turns} onAnswer={answer} streaming={running} animate={animate} />
      </div>
      <footer className="race-lane-foot">
        {isKept ? (
          <span className="race-kept-tag">
            <Check size={13} aria-hidden="true" /> Kept: its changes are in your folder
          </span>
        ) : (
          <button
            className="button"
            onClick={onKeep}
            disabled={running || keeping !== null || turns.length === 0}
            title={running ? "Wait for it to finish" : "Copy what this model changed into your folder"}
          >
            <Trophy size={13} aria-hidden="true" />
            {keeping === id ? "Copying…" : kept ? "Keep this one instead" : "Keep this result"}
          </button>
        )}
      </footer>
    </section>
  );
}
