"use client";

import { ArrowUp, Maximize2, Square } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, sessionSocket, takeFirstPrompt, type DemoInfo, type SessionStatus } from "@/lib/api";
import { buildCalls } from "@/lib/calls";
import { buildTurns, waitingCalls, type RawEvent } from "@/lib/events";
import { AskBar, Conversation, type Answer } from "./Conversation";
import { Inspector, isTab, type InspectorTab } from "./inspector/Inspector";
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
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [demo, setDemo] = useState<DemoInfo | null>(null);
  const socket = useRef<WebSocket | null>(null);
  const scroller = useRef<HTMLDivElement | null>(null);
  const pinned = useRef(true); // whether to follow new output to the bottom

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
          setEvents(backlog);
          // A session started from the home screen arrives with its first task to send.
          const first = backlog.length === 0 ? takeFirstPrompt(id) : null;
          if (first) ws.send(JSON.stringify({ type: "prompt", text: first }));
        } else if (data.type === "server_error") setNotice(String(data.message));
        else setEvents((previous) => [...previous, data]);
      };
      ws.onclose = (event) => {
        if (stopped) return;
        if (event.code === 4401 || event.code === 4404) {
          setConnection("closed");
          setClosedWhy(
            event.code === 4401
              ? "The server refused this browser's token. Open the link zwans serve printed."
              : "That session isn't open in the server. Resume it from the sidebar.",
          );
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
  }, [id, hasToken]);

  useEffect(() => {
    if (!status?.demo || demo) return;
    api<DemoInfo>("/api/demo")
      .then(setDemo)
      .catch(() => undefined);
  }, [status?.demo, demo]);

  const turns = useMemo(() => buildTurns(events), [events]);
  const hood = useMemo(() => buildCalls(events), [events]);
  const waiting = waitingCalls(turns);

  useLayoutEffect(() => {
    const box = scroller.current;
    if (box && pinned.current) box.scrollTop = box.scrollHeight;
  }, [events.length, waiting.length, tab]);

  const send = useCallback((message: Record<string, unknown>) => {
    socket.current?.send(JSON.stringify(message));
  }, []);

  const answer = useCallback(
    (callId: string, value: Answer) => send({ type: "approve", call_id: callId, answer: value }),
    [send],
  );

  const prompt = (text: string) => {
    if (!text.trim()) return;
    setNotice(null);
    pinned.current = true;
    send({ type: "prompt", text: text.trim() });
    setDraft("");
  };

  const openTab = useCallback(
    (next: InspectorTab | null) => {
      const base = `/session/?id=${encodeURIComponent(id)}`;
      router.replace(next ? `${base}&tab=${next}` : base, { scroll: false });
    },
    [id, router],
  );
  const closeInspector = useCallback(() => openTab(null), [openTab]);

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

  return (
    <div className="session">
      <div className="session-main">
        <header className="session-head glass">
          <h1>{status?.title || "New session"}</h1>
          {status && (
            <>
              <span className="pill pill-quiet mono" title={status.workspace}>
                {status.workspace.split("/").filter(Boolean).at(-1)}
              </span>
              <span className="pill pill-quiet">{MODES[status.mode] ?? status.mode}</span>
              {status.demo && <span className="pill">Demo</span>}
            </>
          )}
          <span style={{ flex: 1 }} />
          <button className="button button-quiet" onClick={() => openTab("context")} title="Open the inspector">
            <Maximize2 size={14} aria-hidden="true" />
            Inspect
          </button>
        </header>

        <div
          className="session-scroll"
          ref={scroller}
          onScroll={(e) => {
            const box = e.currentTarget;
            pinned.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
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
            {connection === "closed" && <div className="notice notice-bad">{closedWhy}</div>}
            <Conversation turns={turns} onAnswer={connection === "open" ? answer : undefined} />
            {running && waiting.length === 0 && (
              <p className="muted small pulse" aria-live="polite">
                Working…
              </p>
            )}
          </div>
        </div>

        <div className="composer glass">
          {notice && <div className="notice notice-warn">{notice}</div>}
          {connection === "open" &&
            waiting.map((call) => <AskBar key={call.id} call={call} onAnswer={answer} />)}
          <textarea
            className="textarea"
            rows={1}
            placeholder={
              waiting.length
                ? "Answer the question above first."
                : running
                  ? "Zwans is working. You can write the next task meanwhile."
                  : "Message Zwans. Enter sends, Shift+Enter adds a line."
            }
            aria-label="Message Zwans"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (!running) prompt(draft);
              }
            }}
            disabled={connection !== "open"}
          />
          <div className="composer-foot">
            <span className="muted small">
              {connection === "connecting"
                ? "Connecting…"
                : running
                  ? waiting.length
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
            {running ? (
              <button className="button button-danger" onClick={() => send({ type: "interrupt" })}>
                <Square size={12} aria-hidden="true" />
                Stop
              </button>
            ) : (
              <button
                className="button button-primary icon-button"
                onClick={() => prompt(draft)}
                disabled={connection !== "open" || !draft.trim()}
                aria-label="Send"
              >
                <ArrowUp size={16} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
      </div>
      <UnderTheHood data={hood} status={status} onOpen={openTab} />
    </div>
  );
}
