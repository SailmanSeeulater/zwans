"use client";

import { keyArgument, type Item, type ToolCall, type Turn } from "@/lib/events";
import { DiffBody } from "./DiffBody";

export type Answer = "once" | "always" | "no";

interface Props {
  turns: Turn[];
  /** Set for a live session: lets the user answer permission questions. */
  onAnswer?: (callId: string, answer: Answer) => void;
}

export function Conversation({ turns, onAnswer }: Props) {
  if (turns.length === 0) return <p className="muted">Nothing yet.</p>;
  return (
    <div>
      {turns.map((turn, i) => (
        <section key={i} className="turn">
          {turn.prompt && <div className="prompt">{turn.prompt}</div>}
          {turn.items.map((item, j) => (
            <ItemView key={j} item={item} onAnswer={onAnswer} />
          ))}
          <TurnFoot turn={turn} />
        </section>
      ))}
    </div>
  );
}

function TurnFoot({ turn }: { turn: Turn }) {
  if (!turn.stop) return null;
  const parts = [`${turn.modelCalls} model ${turn.modelCalls === 1 ? "call" : "calls"}`];
  if (turn.stop.reason !== "end_turn") {
    parts.unshift(`Stopped: ${turn.stop.reason}${turn.stop.detail ? `, ${turn.stop.detail}` : ""}`);
  }
  return <div className="turn-foot">{parts.join(" · ")}</div>;
}

function ItemView({ item, onAnswer }: { item: Item; onAnswer?: Props["onAnswer"] }) {
  switch (item.kind) {
    case "text":
      return <div className="model-text">{item.text}</div>;
    case "note":
      return <div className="model-note">{item.text}</div>;
    case "tool":
      return <ToolCard call={item.call} onAnswer={onAnswer} />;
    case "error":
      return <div className="notice notice-bad">Error: {item.message}</div>;
    case "compacted":
      return (
        <div className="muted">
          Older messages summarized: about {item.before.toLocaleString()} → {item.after.toLocaleString()} tokens
        </div>
      );
    case "hook":
      return (
        <div className="notice notice-warn">
          {item.event} hook: {item.message}
        </div>
      );
  }
}

function stateOf(call: ToolCall): { text: string; className: string } {
  const state = call.permission?.state;
  if (state === "asking") return { text: "waiting for you", className: "status-stopped" };
  if (state === "declined") return { text: "declined", className: "status-failed" };
  if (state === "denied") return { text: "refused", className: "status-failed" };
  if (!call.result) return { text: "running…", className: "muted" };
  if (call.result.isError) return { text: "error", className: "status-failed" };
  return { text: "", className: "" };
}

export function ToolCard({ call, onAnswer }: { call: ToolCall; onAnswer?: Props["onAnswer"] }) {
  const state = stateOf(call);
  const diff = call.result?.diff;
  const asking = call.permission?.state === "asking";
  return (
    <>
      <details className={`tool ${call.result?.isError ? "tool-error" : ""}`} open={Boolean(diff) || asking}>
        <summary>
          <span className="tool-name">{call.name}</span>
          <span className="tool-arg" title={keyArgument(call)}>
            {keyArgument(call)}
          </span>
          <span className={`tool-state ${state.className}`}>{state.text}</span>
        </summary>
        <div className="tool-body">
          {call.permission && call.permission.state !== "asking" && (
            <p className="muted">
              {call.permission.reason} ({call.permission.state})
            </p>
          )}
          {call.hooks.map((hook, i) => (
            <p key={i} className="notice notice-warn">
              {hook.event} hook: {hook.message}
            </p>
          ))}
          {diff ? (
            <DiffBody text={diff} />
          ) : (
            <>
              <div className="label">Input</div>
              <pre>{JSON.stringify(call.args, null, 2)}</pre>
            </>
          )}
          {call.result && !diff && (
            <>
              <div className="label">
                Result{call.result.untrusted ? " (untrusted: from a file, command or server)" : ""}
              </div>
              <pre>{call.result.content}</pre>
            </>
          )}
          {call.result && diff && <p className="muted">{call.result.content}</p>}
          {call.subcalls.length > 0 && (
            <div className="subcalls">
              <div className="label">What the subagent did</div>
              {call.subcalls.map((sub) => (
                <ToolCard key={sub.id} call={sub} onAnswer={onAnswer} />
              ))}
            </div>
          )}
        </div>
      </details>
      {/* A live session shows its questions by the composer, where they can't scroll away. */}
      {asking && call.permission && !onAnswer && <AskBar call={call} />}
    </>
  );
}

export function AskBar({ call, onAnswer }: { call: ToolCall; onAnswer?: Props["onAnswer"] }) {
  const always = call.permission?.rules.join(", ") || "this exact call";
  return (
    <div className="ask" role="group" aria-label="Permission request">
      <div className="ask-reason">{call.permission?.reason}</div>
      {onAnswer ? (
        <div className="row">
          <button className="button button-primary" onClick={() => onAnswer(call.id, "once")}>
            Allow once
          </button>
          <button className="button" onClick={() => onAnswer(call.id, "always")} title={always}>
            Always allow ({always})
          </button>
          <button className="button button-danger" onClick={() => onAnswer(call.id, "no")}>
            Deny
          </button>
        </div>
      ) : (
        <p className="muted">Nobody answered.</p>
      )}
    </div>
  );
}
