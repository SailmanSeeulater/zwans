"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { sessionSocket, type SessionStatus } from "@/lib/api";
import { buildTurns, waitingCalls, type RawEvent } from "@/lib/events";
import { AskBar, Conversation, type Answer } from "./Conversation";
import { TokenMissing, useHasToken } from "./useApi";

type Connection = "connecting" | "open" | "closed";

export function SessionView() {
  const id = useSearchParams().get("id") ?? "";
  const hasToken = useHasToken();
  const [events, setEvents] = useState<RawEvent[]>([]);
  const [status, setStatus] = useState<SessionStatus | null>(null);
  const [connection, setConnection] = useState<Connection>("connecting");
  const [closedWhy, setClosedWhy] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const socket = useRef<WebSocket | null>(null);
  const bottom = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!id || !hasToken) return;
    const ws = sessionSocket(id);
    socket.current = ws;
    ws.onopen = () => setConnection("open");
    ws.onmessage = (message) => {
      const data = JSON.parse(String(message.data)) as RawEvent;
      if (data.type === "status") setStatus(data as unknown as SessionStatus);
      else if (data.type === "backlog") setEvents((data.events as RawEvent[]) ?? []);
      else if (data.type === "server_error") setNotice(String(data.message));
      else setEvents((previous) => [...previous, data]);
    };
    ws.onclose = (event) => {
      setConnection("closed");
      setClosedWhy(
        event.code === 4401
          ? "The server refused this browser's token. Open the link zwans serve printed."
          : event.code === 4404
            ? "That session isn't open in the server. Resume it from the sessions page."
            : "Lost the connection to the server.",
      );
    };
    return () => ws.close();
  }, [id, hasToken]);

  const turns = useMemo(() => buildTurns(events), [events]);
  const waiting = waitingCalls(turns);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [events.length]);

  const send = useCallback((message: Record<string, unknown>) => {
    socket.current?.send(JSON.stringify(message));
  }, []);

  const answer = useCallback(
    (callId: string, value: Answer) => send({ type: "approve", call_id: callId, answer: value }),
    [send],
  );

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    setNotice(null);
    send({ type: "prompt", text });
    setDraft("");
  };

  if (hasToken === false) {
    return (
      <main className="page">
        <TokenMissing />
      </main>
    );
  }

  const running = status?.running ?? false;
  return (
    <main className="page">
      <header className="session-head">
        <h1>{status?.title || "New session"}</h1>
        {status && (
          <div className="row muted mono" style={{ fontSize: 13 }}>
            <span>{status.workspace}</span>
            <span>·</span>
            <span>{status.model}</span>
            <span>·</span>
            <span>mode {status.mode}</span>
            <span>·</span>
            <span>{status.executor}</span>
            <span>·</span>
            <span>${status.dollars.toFixed(4)}</span>
            <span>·</span>
            <span>context ~{status.context_tokens.toLocaleString()} tokens</span>
          </div>
        )}
      </header>

      {status?.warnings.map((warning) => (
        <div key={warning} className="notice notice-warn">
          {warning}
        </div>
      ))}
      {connection === "closed" && <div className="notice notice-bad">{closedWhy}</div>}

      <Conversation turns={turns} onAnswer={connection === "open" ? answer : undefined} />
      <div ref={bottom} />

      <div className="composer">
        {notice && <div className="notice notice-warn">{notice}</div>}
        {connection === "open" && waiting.map((call) => <AskBar key={call.id} call={call} onAnswer={answer} />)}
        <textarea
          className="textarea"
          placeholder={
            waiting.length
              ? "Answer the question above first."
              : running
                ? "Zwans is working. You can type the next task meanwhile."
                : "What should Zwans do? Enter sends, Shift+Enter adds a line."
          }
          aria-label="Next task"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!running) submit();
            }
          }}
          disabled={connection !== "open"}
        />
        <div className="row" style={{ marginTop: 8, justifyContent: "space-between" }}>
          <span className="muted" style={{ fontSize: 13 }}>
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
          <div className="row">
            {running && (
              <button className="button button-danger" onClick={() => send({ type: "interrupt" })}>
                Interrupt
              </button>
            )}
            <button className="button button-primary" onClick={submit} disabled={running || connection !== "open" || !draft.trim()}>
              Send
            </button>
          </div>
        </div>
      </div>
    </main>
  );
}
