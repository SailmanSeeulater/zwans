"use client";

import { ArrowUp, Check, CornerDownRight, ImagePlus, Maximize2, MonitorPlay, PanelRightOpen, Repeat, RotateCcw, Share2, ShieldAlert, Square, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  api,
  download,
  sessionSocket,
  takeFirstPrompt,
  type DemoInfo,
  type TrustQuestion,
  type FileChange,
  type RewindResult,
  type SessionStatus,
  type SessionChanges,
  type UndoableTurns,
} from "@/lib/api";
import {
  attachProblem,
  changesFrom,
  describeUndo,
  IMAGE_TYPES,
  readAttachment,
  type Attachment,
} from "@/lib/attachments";
import { buildCalls } from "@/lib/calls";
import { buildTurns, pendingQuestion, waitingCalls, type RawEvent } from "@/lib/events";
import { CHANGES, DEFAULT_PANE, readPane, savePane, tabLabel, withNewPage, type PaneState } from "@/lib/pane";
import { fileChanges, latestServer } from "@/lib/preview";
import { handoffPrompt, modelName, stuckReason } from "@/lib/handoff";
import { budgetLevel, COMMANDS, fromFiles, loopState, matching, parseCommand, type Parsed } from "@/lib/commands";
import { dollars as money } from "@/lib/format";
import { currentTodos } from "@/lib/todos";
import { livenessOf, phaseOf, tabTitle, turnStartedAt } from "@/lib/working";
import { AskBar, Conversation, type Answer } from "./Conversation";
import { JumpToLatest, typing } from "./Actions";
import { ActivityStrip, ContextMeter } from "./Glance";
import { Spark, WorkingLine } from "./Working";
import { Inspector, isTab, type InspectorTab } from "./inspector/Inspector";
import { ModelPicker } from "./ModelPicker";
import { TodoList } from "./TodoList";
import { ChangesPanel } from "./ChangesPanel";
import { SidePane } from "./SidePane";
import { UnderTheHood } from "./UnderTheHood";
import { TokenMissing, useHasToken } from "./useApi";

type Connection = "connecting" | "open" | "closed";

const RECONNECT_MS = 1_000;
const MODES: Record<string, string> = { ask: "Ask before changes", auto: "Auto", "read-only": "Read-only" };

export function SessionView() {
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id") ?? "";
  const tabParam = params.get("tab");
  const tab: InspectorTab | null = isTab(tabParam) ? tabParam : null;
  const hasToken = useHasToken();
  const [events, setEvents] = useState<RawEvent[]>([]);
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [closedWhy, setClosedWhy] = useState("");
  const [resumable, setResumable] = useState(false); // closed because the server doesn't have it open
  const [resuming, setResuming] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [trustAsk, setTrustAsk] = useState<TrustQuestion | null>(null);
  const [draft, setDraft] = useState("");
  const [demo, setDemo] = useState<DemoInfo | null>(null);
  const [images, setImages] = useState<Attachment[]>([]);
  const [undoable, setUndoable] = useState<UndoableTurns | null>(null);
  const [changes, setChanges] = useState<SessionChanges | null>(null);
  const [undoing, setUndoing] = useState<number | null>(null); // the turn whose undo is being confirmed
  const [undoBusy, setUndoBusy] = useState(false);
  const [generation, setGeneration] = useState(0); // bumped when the session is reopened, to reconnect
  const [animate, setAnimate] = useState(false); // whether new items ease in: not the backlog
  const picker = useRef<HTMLInputElement | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true); // whether to follow new output to the bottom
  const autoResumed = useRef(""); // the session this page has already tried to resume by itself
  const resend = useRef<string | null>(null); // a prompt to send once the session reconnects: a retry
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [fresh, setFresh] = useState(false); // something arrived while scrolled up

  const resume = useCallback(async () => {
    setResuming(true);
    try {
      await api<SessionStatus>(`/api/sessions/${encodeURIComponent(id)}/open`, { method: "POST" });
      setNotice(null);
      setConnection("connecting");
      setGeneration((g) => g + 1);
    } catch (error) {
      setNotice(`Couldn't resume it: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setResuming(false);
    }
  }, [id]);

  useEffect(() => {
    if (!id || !hasToken) return;
    let stopped = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let ws: WebSocket;
    const connect = () => {
      ws = sessionSocket(id);
      socket.current = ws;
      ws.onopen = () => setConnection("open");
      ws.onmessage = (message) => {
        const data = JSON.parse(String(message.data)) as RawEvent;
        if (data.type === "status") setStatus(data as unknown as SessionStatus);
        else if (data.type === "backlog") {
          const backlog = (data.events as RawEvent[]) ?? [];
          setAnimate(false);
          setEvents(backlog);
          // Once the backlog is on screen, what arrives after it eases in.
          requestAnimationFrame(() => requestAnimationFrame(() => setAnimate(true)));
          // A session started from the home screen arrives with its first task to send.
          const first = backlog.length === 0 ? takeFirstPrompt(id) : null;
          if (first) ws.send(JSON.stringify({ type: "prompt", text: first }));
          else if (resend.current) {
            ws.send(JSON.stringify({ type: "prompt", text: resend.current }));
            resend.current = null;
          }
        } else if (data.type === "server_error") setNotice(String(data.message));
        else if (data.type === "command_needs_trust") setTrustAsk(data as unknown as TrustQuestion);
        else setEvents((previous) => [...previous, data]);
      };
      ws.onclose = (event) => {
        if (stopped) return;
        if (event.code === 4401 || event.code === 4404) {
          setConnection("closed");
          setResumable(event.code === 4404);
          setClosedWhy(
            event.code === 4401
              ? "The server refused this browser's token. Open the link zwans serve printed."
              : "This session isn't open in the server, which happens after the server restarts.",
          );
          // A saved session only needs opening again, so try that once without being asked.
          if (event.code === 4404 && autoResumed.current !== id) {
            autoResumed.current = id;
            void resume();
          }
          return;
        }
        // A laptop's sleep or a network blip. The backlog on reconnecting fills in what was missed.
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
  }, [id, hasToken, generation, resume]);

  useEffect(() => {
    if (!status?.demo || demo) return;
    api<DemoInfo>("/api/demo")
      .then(setDemo)
      .catch(() => undefined);
  }, [status?.demo, demo]);

  const turns = useMemo(() => buildTurns(events), [events]);
  const turnCount = turns.length;
  const custom = fromFiles(status?.commands); // commands from .zwans/commands files
  const idle = status !== null && !status.running;

  // What can be undone changes as turns finish, so ask again whenever the session settles.
  useEffect(() => {
    if (!id || !hasToken || !idle) return;
    let current = true;
    api<UndoableTurns>(`/api/sessions/${encodeURIComponent(id)}/turns`)
      .then((found) => current && setUndoable(found))
      .catch(() => current && setUndoable(null));
    return () => {
      current = false;
    };
  }, [id, hasToken, idle, turnCount, generation]);
  const hood = useMemo(() => buildCalls(events), [events]);

  const [pane, setPane] = useState<PaneState>(DEFAULT_PANE);
  useEffect(() => {
    // localStorage only exists in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setPane(readPane());
  }, []);
  const changePane = useCallback((next: PaneState) => {
    setPane(next);
    savePane(next);
  }, []);
  // What the session has changed: asked for whenever it settles, and as tool calls finish
  // while the Changes tab is showing, so the list grows as the files do.
  const finished = useMemo(() => events.filter((e) => e.type === "tool_result").length, [events]);
  const watchingChanges = pane.open && pane.active === CHANGES;
  const changesFor = idle || watchingChanges ? finished : -1;
  useEffect(() => {
    if (!id || !hasToken || changesFor < 0) return;
    let current = true;
    const ask = setTimeout(() => {
      api<SessionChanges>(`/api/sessions/${encodeURIComponent(id)}/changes`)
        .then((found) => current && setChanges(found))
        .catch(() => undefined);
    }, idle ? 0 : 400);
    return () => {
      current = false;
      clearTimeout(ask);
    };
  }, [id, hasToken, idle, changesFor, turnCount, generation]);
  // While the pane's edge is dragged, a conversation that was following new output keeps
  // its last line in view as its text rewraps.
  const followWhileResizing = useCallback(() => {
    const box = scroller.current;
    if (box && pinned.current) box.scrollTop = box.scrollHeight;
  }, []);
  const waiting = waitingCalls(turns);
  // The model's own question, which the composer answers while it's waiting.
  const question = connection === "open" ? pendingQuestion(turns) : null;
  const todos = currentTodos(turns);
  const liveness = livenessOf(status);

  useEffect(() => {
    const title = status?.title || (status?.chat ? "New chat" : status ? "New session" : "");
    document.title = tabTitle(title, liveness, status?.waiting_for.length ?? 0);
    return () => {
      document.title = "Zwans";
    };
  }, [status, liveness]);

  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && pinned.current) box.scrollTop = box.scrollHeight;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- marks what arrived out of view
    else if (events.length) setFresh(true);
  }, [events.length, waiting.length, tab]);

  const jumpToLatest = useCallback(() => {
    const box = scroller.current;
    if (!box) return;
    pinned.current = true;
    setFresh(false);
    box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
  }, []);

  const send = useCallback((message: Record<string, unknown>) => {
    socket.current?.send(JSON.stringify(message));
  }, []);

  const answer = useCallback(
    (callId: string, value: Answer) => send({ type: "approve", call_id: callId, answer: value }),
    [send],
  );

  const runCommand = (command: Parsed) => {
    if (command.name === "unknown") {
      const names = [...COMMANDS, ...custom].map((c) => `/${c.name}`);
      const broken = status?.command_problems?.find((p) => p.startsWith(`${command.typed.slice(1)}.md`));
      setNotice(broken ?? `There's no ${command.typed}. The commands are ${names.join(", ")}.`);
      return;
    }
    setNotice(null);
    if (command.name === "custom") {
      pinned.current = true;
      send({ type: "command", name: command.command, argument: command.argument });
    } else if (command.name === "loop") {
      if (!command.argument) {
        setNotice("Say what to check: /loop until pytest -q, or /loop 8 until \"npm test\" fix the dates.");
        return;
      }
      pinned.current = true;
      send({ type: "loop", argument: command.argument });
    } else if (!command.argument) {
      const cap = status?.budget;
      const spent = status?.dollars ?? 0;
      setNotice(
        cap == null
          ? `No budget: ${money(spent)} spent so far. /budget 2 sets one.`
          : `${money(spent)} of ${money(cap)} spent. /budget off clears it.`,
      );
      return;
    } else {
      send({ type: "budget", dollars: command.argument });
    }
    setDraft("");
  };

  const prompt = (text: string) => {
    if (!text.trim() && images.length === 0) return;
    const command = images.length === 0 ? parseCommand(text, custom) : null;
    if (command) {
      runCommand(command);
      return;
    }
    setNotice(null);
    pinned.current = true;
    const message: Record<string, unknown> = { type: "prompt", text: text.trim() };
    if (images.length) message.images = images.map(({ name, data }) => ({ name, data }));
    send(message);
    setDraft("");
    setImages([]);
  };

  const answerQuestion = (text: string) => {
    if (!text.trim()) return;
    pinned.current = true;
    send({ type: "answer", text: text.trim() });
    setDraft("");
  };

  const attach = async (files: Iterable<File>) => {
    let count = images.length;
    const added: Attachment[] = [];
    for (const file of files) {
      const problem = attachProblem(file, count);
      if (problem) {
        setNotice(problem);
        continue;
      }
      try {
        added.push(await readAttachment(file));
        count += 1;
      } catch (error) {
        setNotice(error instanceof Error ? error.message : String(error));
      }
    }
    if (added.length) setImages((previous) => [...previous, ...added]);
  };

  const undo = async (turn: number, again = false) => {
    setUndoBusy(true);
    try {
      const result = await api<RewindResult>(`/api/sessions/${encodeURIComponent(id)}/rewind`, {
        method: "POST",
        body: JSON.stringify({ turn }),
      });
      setUndoing(null);
      setStatus(result.status);
      setEvents([]);
      setUndoable(null);
      const hadImages = turns.find((t) => t.number === turn)?.images ?? 0;
      if (again && !hadImages && result.draft.trim()) {
        resend.current = result.draft; // sent as soon as the session is back
        pinned.current = true;
        setNotice(null);
      } else {
        setDraft(result.draft);
        const reattach = hadImages ? " Its images weren't kept: attach them again to resend it." : "";
        setNotice(`Went back to before turn ${turn}. ${describeUndo(result.undone)}${reattach}`);
      }
      setGeneration((g) => g + 1);
    } catch (error) {
      setNotice(`Couldn't undo: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setUndoBusy(false);
    }
  };

  const openTab = useCallback(
    (next: InspectorTab | null) => {
      const base = `/session/?id=${encodeURIComponent(id)}`;
      router.replace(next ? `${base}&tab=${next}` : base, { scroll: false });
    },
    [id, router],
  );
  const closeInspector = useCallback(() => openTab(null), [openTab]);
  const [sharing, setSharing] = useState(false);
  const [shared, setShared] = useState(false);
  const shareReplay = async () => {
    setSharing(true);
    try {
      const name = await download(`/api/sessions/${encodeURIComponent(id)}/replay`, `zwans-replay-${id}.html`);
      setNotice(`Saved ${name}: it plays this session back in any browser, so you can send it to anyone. Keys and tokens are masked.`);
      setShared(true);
      setTimeout(() => setShared(false), 2_400);
    } catch (error) {
      setNotice(`Couldn't make the replay: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSharing(false);
    }
  };
  const loop = useMemo(() => loopState(events), [events]);
  const menu = matching(draft, custom);

  // Local first: when a turn on a model on this machine gets stuck, offer to hand the task
  // to the stronger model the config names. Nothing is sent until the person says so.
  const lastTurn = turns.at(-1);
  const stuck = status?.local && status.handoff_model && !status.running ? stuckReason(lastTurn) : null;
  const [handoffDismissed, setHandoffDismissed] = useState<number | null>(null);
  const [handingOff, setHandingOff] = useState(false);
  const offerHandoff = stuck !== null && connection === "open" && handoffDismissed !== lastTurn?.number;
  const handOff = async () => {
    if (!status?.handoff_model || !stuck) return;
    const from = modelName(status.model);
    setHandingOff(true);
    try {
      const next = await api<SessionStatus>(`/api/sessions/${encodeURIComponent(id)}/model`, {
        method: "POST",
        body: JSON.stringify({ name: status.handoff_model }),
      });
      setStatus(next);
      setNotice(null);
      pinned.current = true;
      send({ type: "prompt", text: handoffPrompt(from, stuck) });
    } catch (error) {
      setNotice(`Couldn't hand off: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setHandingOff(false);
    }
  };

  // Live preview: a dev server the session's commands started is offered beside the
  // conversation, once, and pages set to live reload when files change.
  const server = useMemo(() => latestServer(turns), [turns]);
  const changedFiles = useMemo(() => fileChanges(turns), [turns]);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const serverOpen = server !== null && pane.pages.some((p) => p.url === server);
  const offerServer = server !== null && !serverOpen && dismissed !== server;
  const previewServer = () => {
    if (!server) return;
    changePane(withNewPage(pane, `p${Date.now().toString(36)}`, server, true));
  };

  // Esc stops a turn, / goes to the message box, J to the latest message, and the
  // platform's modifier with \\ shows or hides the side pane.
  const runningNow = status?.running ?? false;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      if (event.key === "Escape" && runningNow && (!typing(event) || event.target === composer.current)) {
        send({ type: "interrupt" });
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key === "\\") {
        event.preventDefault();
        changePane({ ...pane, open: !pane.open });
        return;
      }
      if (typing(event) || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "/") {
        event.preventDefault();
        composer.current?.focus();
      } else if (event.key === "j") {
        jumpToLatest();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [runningNow, send, pane, changePane, jumpToLatest]);

  if (hasToken === false) {
    return (
      <main className="page">
        <TokenMissing />
      </main>
    );
  }

  if (tab) {
    return (
      <Inspector
        tab={tab}
        onTab={openTab}
        onClose={closeInspector}
        sessionId={id}
        status={status}
        events={events}
        data={hood}
      />
    );
  }

  const running = status?.running ?? false;
  const nextDemoPrompt = demo && !running ? demo.prompts[turns.filter((t) => t.prompt).length] : undefined;
  const warnings = (status?.warnings ?? []).filter((w) => !(status?.demo && w === demo?.note));

  const hasPane = Boolean(status) || connection !== "closed";

  return (
    <div className="session" style={{ "--pane-width": `${pane.width}px` } as CSSProperties}>
      <div className="session-main">
        <header className="session-head glass">
          <h1 title={status?.title || undefined}>
            {status?.title || (connection === "closed" ? "Session" : status?.chat ? "New chat" : "New session")}
          </h1>
          {status && (
            <>
              {status.chat ? (
                <span className="pill pill-quiet" title="No project folder, and no file or command tools">
                  Chat
                </span>
              ) : (
                <>
                  <span className="pill pill-quiet mono" title={status.workspace}>
                    {status.workspace.split("/").filter(Boolean).at(-1)}
                  </span>
                  <span className="pill pill-quiet">{MODES[status.mode] ?? status.mode}</span>
                </>
              )}
              {!status.demo && (
                <ModelPicker
                  model={status.model}
                  disabled={running || connection !== "open"}
                  onChoose={async (name) => {
                    const next = await api<SessionStatus>(`/api/sessions/${encodeURIComponent(id)}/model`, {
                      method: "POST",
                      body: JSON.stringify({ name }),
                    });
                    setStatus(next);
                    setNotice(`Switched to ${next.model}. The next message goes to it.`);
                  }}
                  onError={setNotice}
                />
              )}
              {status.demo && <span className="pill">Demo</span>}
            </>
          )}
          <span style={{ flex: 1 }} />
          {status && status.budget != null && (
            <span
              className="budget-pill"
              data-level={budgetLevel(status.dollars, status.budget)}
              title={`Budget: ${money(status.dollars)} of ${money(status.budget)} spent. /budget changes it.`}
            >
              <span className="budget-bar" aria-hidden="true">
                <span style={{ width: `${Math.min(100, (status.dollars / (status.budget || 1)) * 100)}%` }} />
              </span>
              {money(status.dollars)} / {money(status.budget)}
            </span>
          )}
          {status && status.context_tokens > 0 && (
            <ContextMeter
              tokens={status.context_tokens}
              compactAt={status.compact_at ?? 200_000}
              onOpen={() => openTab("context")}
            />
          )}
          <button
            className="button button-quiet icon-button share-button"
            onClick={() => void shareReplay()}
            disabled={turnCount === 0 || sharing}
            title="Share a replay: save this session as one HTML file that plays it back, to send to anyone"
            aria-label={shared ? "Replay saved" : "Share a replay"}
            data-saved={shared || undefined}
            style={shared ? { color: "var(--ok)" } : undefined}
          >
            {shared ? <Check size={14} aria-hidden="true" /> : <Share2 size={14} aria-hidden="true" />}
          </button>
          <button className="button button-quiet" onClick={() => openTab("context")} title="Open the inspector">
            <Maximize2 size={14} aria-hidden="true" />
            Inspect
          </button>
          {hasPane && !pane.open && (
            <button
              className="button button-quiet icon-button pane-show"
              onClick={() => changePane({ ...pane, open: true })}
              aria-label="Show the side pane"
              title="Show the side pane"
            >
              <PanelRightOpen size={14} aria-hidden="true" />
            </button>
          )}
        </header>

        <div className="session-body">
        <ActivityStrip turns={turns} />
        <div
          className="session-scroll"
          ref={scroller}
          onScroll={(e) => {
            const box = e.currentTarget;
            pinned.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
            if (pinned.current !== atBottom) setAtBottom(pinned.current);
            if (pinned.current && fresh) setFresh(false);
          }}
        >
          <div className="session-column">
            {status?.demo && demo && (
              <div className="callout">
                <div className="callout-title">Demo</div>
                {demo.note}
              </div>
            )}
            {warnings.map((warning) => (
              <div key={warning} className="notice notice-warn">
                {warning}
              </div>
            ))}
            {(turns.length > 0 || connection !== "closed") && (
              <Conversation
                turns={turns}
                onAnswer={connection === "open" ? answer : undefined}
                undoable={running ? undefined : new Set(undoable?.turns.map((t) => t.turn) ?? [])}
                onUndo={connection === "open" ? setUndoing : undefined}
                streaming={running}
                animate={animate}
                onRetry={connection === "open" && !running ? (turn) => void undo(turn, true) : undefined}
              />
            )}
            {offerHandoff && status?.handoff_model && (
              <div className="handoff" role="group" aria-label="Hand off">
                <Spark size={16} still />
                <div className="handoff-text">
                  <strong>{modelName(status.model)} seems stuck.</strong> It {stuck}. Hand the task to{" "}
                  {modelName(status.handoff_model)}? It picks up with the whole conversation so far, and its calls
                  cost money.
                </div>
                <div className="handoff-actions">
                  <button className="button button-primary button-small" onClick={() => void handOff()} disabled={handingOff}>
                    {handingOff ? "Handing off…" : `Hand off to ${modelName(status.handoff_model).replace(/^Claude /, "")}`}
                  </button>
                  <button className="button button-quiet button-small" onClick={() => setHandoffDismissed(lastTurn?.number ?? 0)}>
                    Keep going here
                  </button>
                </div>
              </div>
            )}
            {running && waiting.length === 0 && !question && (
              <WorkingLine
                phase={phaseOf(turns)}
                startedAt={turnStartedAt(events)}
                outputTokens={turns.at(-1)?.outputTokens ?? 0}
              />
            )}
          </div>
        </div>
        <JumpToLatest shown={!atBottom} fresh={fresh} onJump={jumpToLatest} />
        </div>

        {connection === "closed" && (
          <div className="composer glass">
            <div className="notice notice-bad">{closedWhy}</div>
            {notice && <div className="notice notice-warn">{notice}</div>}
            {resumable && (
              <div className="row">
                <button className="button button-primary" onClick={() => void resume()} disabled={resuming}>
                  {resuming ? "Resuming…" : "Try again"}
                </button>
                <Link className="button" href="/">
                  New session
                </Link>
              </div>
            )}
          </div>
        )}
        <div
          className="composer glass"
          style={connection === "closed" ? { display: "none" } : undefined}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("Files")) e.preventDefault();
          }}
          onDrop={(e) => {
            if (!e.dataTransfer.files.length) return;
            e.preventDefault();
            void attach(Array.from(e.dataTransfer.files));
          }}
        >
          {notice && <div className="notice notice-warn">{notice}</div>}
          {offerServer && server && (
            <div className="server-found" role="status">
              <span className="server-found-dot" aria-hidden="true" />
              <span className="server-found-text">
                A dev server is up at <span className="mono">{tabLabel(server)}</span>
              </span>
              <button className="button button-primary button-small" onClick={previewServer}>
                <MonitorPlay size={13} aria-hidden="true" />
                Preview
              </button>
              <button
                className="button button-quiet icon-button"
                onClick={() => setDismissed(server)}
                aria-label="Not now"
                title="Not now"
              >
                <X size={13} aria-hidden="true" />
              </button>
            </div>
          )}
          {running && loop?.active && (
            <div className="loop-chip" role="status">
              <Spark size={13} />
              <span>
                Looping until <span className="mono">{loop.check}</span>
              </span>
              <span className="loop-chip-count">
                turn {Math.min(loop.round + 1, loop.rounds)} of {loop.rounds}
              </span>
            </div>
          )}
          {trustAsk && (
            <div className="trust-ask" role="alertdialog" aria-label="Trust this command?">
              <ShieldAlert size={16} aria-hidden="true" />
              <div className="trust-ask-text">
                <strong>/{trustAsk.name} runs a command from this project</strong>
                <span className="muted small">
                  <span className="mono">{trustAsk.path}</span> came with the folder and runs{" "}
                  <code>{trustAsk.check}</code> after each turn. Trust it as it is now? A change to the file asks again.
                </span>
              </div>
              <button className="button button-quiet" onClick={() => setTrustAsk(null)}>
                Cancel
              </button>
              <button
                className="button button-primary"
                onClick={() => {
                  pinned.current = true;
                  send({ type: "command", name: trustAsk.name, argument: trustAsk.argument, trust: true });
                  setTrustAsk(null);
                  setDraft("");
                }}
              >
                Trust and run
              </button>
            </div>
          )}
          {menu.length > 0 && (
            <ul className="slash-menu" role="listbox" aria-label="Commands">
              {menu.map((command) => (
                <li key={command.name}>
                  <button
                    role="option"
                    aria-selected={false}
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setDraft(`/${command.name} `);
                      composer.current?.focus();
                    }}
                  >
                    <span className="mono slash-name">/{command.name}</span>
                    <span className="mono muted small">{command.args}</span>
                    <span className="slash-about">{command.about}</span>
                    {command.scope && (
                      <span className="slash-scope" title={command.check ? `Loops until ${command.check} passes` : undefined}>
                        {command.check ? <Repeat size={11} aria-hidden="true" /> : null}
                        {command.scope === "project" ? "project" : "yours"}
                      </span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {running && (status?.queued?.length ?? 0) > 0 && (
            <ul className="queued" aria-label="Sent, waiting for Zwans's next step">
              {status?.queued?.map((text, i) => (
                <li key={i} className="queued-item">
                  <span className="queued-dot" aria-hidden="true" />
                  <span className="queued-text">{text}</span>
                  <span className="muted small">at the next step</span>
                </li>
              ))}
            </ul>
          )}
          {undoing !== null && !running && (
            <UndoConfirm
              turn={undoing}
              files={changesFrom(undoable?.turns ?? [], undoing)}
              busy={undoBusy}
              onUndo={() => void undo(undoing)}
              onCancel={() => setUndoing(null)}
            />
          )}
          {/* The plan stays in view while it's being worked through, but gives way to a
              question, so the buttons to answer it always fit. */}
          {running && waiting.length === 0 && !question && todos && todos.length > 0 && (
            <TodoList todos={todos} />
          )}
          {connection === "open" &&
            waiting.map((call) => <AskBar key={call.id} call={call} onAnswer={answer} />)}
          {question && waiting.length === 0 && (
            <div className="ask" role="group" aria-label="Question from Zwans">
              <div className="ask-reason">{question.question}</div>
              {question.options.length > 0 && (
                <div className="row">
                  {question.options.map((option, i) => (
                    <button
                      key={option}
                      className={i === 0 ? "button button-primary" : "button"}
                      onClick={() => answerQuestion(option)}
                    >
                      {option}
                    </button>
                  ))}
                </div>
              )}
              <p className="muted small" style={{ margin: "8px 0 0" }}>
                {question.options.length > 0 ? "Or type your own answer below." : "Type your answer below."}
              </p>
            </div>
          )}
          <textarea
            ref={composer}
            className="textarea"
            rows={1}
            placeholder={
              question && waiting.length === 0
                ? "Type your answer. Enter sends it."
                : waiting.length
                  ? "Answer the question above first."
                  : running
                  ? "Steer Zwans: what you send now reaches it at its next step."
                  : status?.chat
                    ? "Ask Zwans anything. Enter sends, Shift+Enter adds a line."
                    : "Message Zwans. Enter sends, Shift+Enter adds a line."
            }
            aria-label="Message Zwans"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onPaste={(e) => {
              const files = Array.from(e.clipboardData.files).filter((f) => f.type.startsWith("image/"));
              if (!files.length) return;
              e.preventDefault();
              void attach(files);
            }}
            onKeyDown={(e) => {
              if (e.key === "Tab" && menu.length > 0 && menu[0]) {
                e.preventDefault();
                setDraft(`/${menu[0].name} `);
                return;
              }
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (question && waiting.length === 0) answerQuestion(draft);
                else if (!running) prompt(draft);
                else if (waiting.length === 0 && images.length === 0) prompt(draft); // steers the turn
              }
            }}
            disabled={connection !== "open"}
          />
          {images.length > 0 && (
            <div className="attachments">
              {images.map((image, i) => (
                <div key={i} className="attachment" title={image.name}>
                  {/* A data: URL thumbnail; next/image has nothing to optimize here. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={image.url} alt={image.name} />
                  <button
                    className="attachment-remove"
                    onClick={() => setImages((previous) => previous.filter((_, j) => j !== i))}
                    aria-label={`Remove ${image.name}`}
                  >
                    <X size={12} aria-hidden="true" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <input
            ref={picker}
            type="file"
            accept={IMAGE_TYPES.join(",")}
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) void attach(Array.from(e.target.files));
              e.target.value = "";
            }}
          />
          <div className="composer-foot">
            <button
              className="button button-quiet icon-button"
              onClick={() => picker.current?.click()}
              disabled={connection !== "open"}
              aria-label="Attach images"
              title="Attach images (or paste or drop them here)"
            >
              <ImagePlus size={15} aria-hidden="true" />
            </button>
            <span className="muted small">
              {connection === "connecting"
                ? "Connecting…"
                : running
                  ? waiting.length || question
                    ? "Waiting for your answer."
                    : "Working…"
                  : connection === "open"
                    ? "Ready."
                    : ""}
            </span>
            {nextDemoPrompt && !draft && (
              <button className="chip" onClick={() => prompt(nextDemoPrompt)} title="The demo is scripted for this">
                {nextDemoPrompt}
              </button>
            )}
            <span style={{ flex: 1 }} />
            {running && draft.trim() && waiting.length === 0 && !question && images.length === 0 && (
              <button
                className="button button-primary steer-send"
                onClick={() => prompt(draft)}
                disabled={connection !== "open"}
                title="Send it to Zwans now: it reads it at its next step, without stopping"
              >
                <CornerDownRight size={13} aria-hidden="true" />
                Steer
              </button>
            )}
            {running ? (
              <button className="button button-danger" onClick={() => send({ type: "interrupt" })}>
                <Square size={12} aria-hidden="true" />
                Stop
              </button>
            ) : (
              <button
                className="button button-primary icon-button"
                onClick={() => prompt(draft)}
                disabled={connection !== "open" || (!draft.trim() && images.length === 0)}
                aria-label="Send"
              >
                <ArrowUp size={16} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </div>
      {hasPane && pane.open && (
        <SidePane
          state={pane}
          onChange={changePane}
          onResizeFrame={followWhileResizing}
          hood={<UnderTheHood data={hood} status={status} onOpen={openTab} />}
          changes={
            <ChangesPanel
              data={changes}
              undoable={undoable}
              onUndo={connection === "open" && !running ? setUndoing : undefined}
            />
          }
          changed={changes?.changes.length ?? 0}
          fileChanges={changedFiles}
        />
      )}
    </div>
  );
}

function UndoConfirm(props: {
  turn: number;
  files: FileChange[];
  busy: boolean;
  onUndo: () => void;
  onCancel: () => void;
}) {
  const { turn, files, busy, onUndo, onCancel } = props;
  const shown = files.slice(0, 6);
  return (
    <div className="ask" role="group" aria-label="Undo">
      <div className="ask-reason">
        Undo turn {turn} and everything after it? The conversation goes back to before it, and its prompt comes
        back to edit.
      </div>
      {files.length > 0 ? (
        <ul className="small mono">
          {shown.map((f) => (
            <li key={f.path}>
              {f.status === "added" ? "remove " : "restore "}
              {f.path}
            </li>
          ))}
          {files.length > shown.length && <li>and {files.length - shown.length} more</li>}
        </ul>
      ) : (
        <p className="muted small">No files in the workspace changed since then.</p>
      )}
      <p className="muted small">Changes outside the workspace, such as commands&apos; side effects, stay.</p>
      <div className="row">
        <button className="button button-danger" onClick={onUndo} disabled={busy}>
          <RotateCcw size={13} aria-hidden="true" />
          {busy ? "Undoing…" : "Undo"}
        </button>
        <button className="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
      </div>
    </div>
  );
}
