"use client";

import { ImageIcon, RotateCcw } from "lucide-react";
import {
  canAlwaysAllow,
  diffOf,
  keyArgument,
  writeKind,
  type Item,
  type ToolCall,
  type Turn,
} from "@/lib/events";
import { lastLine } from "@/lib/format";
import { TODO_TOOL, todosOf } from "@/lib/todos";
import { DiffBody } from "./DiffBody";
import { DiffCount } from "./Glance";
import { Markdown } from "./Markdown";
import { Ticks } from "./Ticks";
import { TodoList } from "./TodoList";

export type Answer = "once" | "always" | "no";

interface Props {
  turns: Turn[];
  /** Set for a live session: lets the user answer permission questions. */
  onAnswer?: (callId: string, answer: Answer) => void;
  /** Turns that can be undone, by number, and what to do when one is chosen. */
  undoable?: Set<number>;
  onUndo?: (turn: number) => void;
}

export function Conversation({ turns, onAnswer, undoable, onUndo }: Props) {
  if (turns.length === 0) return <p className="muted">Nothing yet.</p>;
  return (
    <div>
      {turns.map((turn, i) => (
        <section key={i} className="turn">
          {(turn.prompt || turn.images > 0) && (
            <div className="prompt-row">
              {onUndo && undoable?.has(turn.number) && (
                <button
                  className="button button-quiet undo-button"
                  onClick={() => onUndo(turn.number)}
                  aria-label={`Undo turn ${turn.number}`}
                  title="Put the files back as they were before this turn, and drop it and later turns"
                >
                  <RotateCcw size={13} aria-hidden="true" />
                  Undo
                </button>
              )}
              <div className="prompt">
                {turn.prompt}
                {turn.images > 0 && (
                  <span className="prompt-images">
                    <ImageIcon size={13} aria-hidden="true" />
                    {turn.images === 1 ? "1 image" : `${turn.images} images`}
                  </span>
                )}
              </div>
            </div>
          )}
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
      return <Markdown text={item.text} />;
    case "note":
      return <Thinking text={item.text} />;
    case "tool":
      if (item.call.name === TODO_TOOL && !item.call.result?.isError) return <TodoCard call={item.call} />;
      return <ToolCard call={item.call} onAnswer={onAnswer} />;
    case "error":
      return <div className="notice notice-bad">Error: {item.message}</div>;
    case "compacted":
      return (
        <details className="compacted">
          <summary>
            Compacted: the older messages became a summary, about {item.before.toLocaleString()} →{" "}
            {item.after.toLocaleString()} tokens
          </summary>
          {item.summary && <Markdown text={item.summary} />}
        </details>
      );
    case "hook":
      return (
        <div className="notice notice-warn">
          {item.event === "follow_through"
            ? "Sent back: its reply left the work undone."
            : `${item.event} hook: ${item.message}`}
        </div>
      );
  }
}

/** The model's thinking, folded away so the answer and the tool calls stay in view. The one
 * line that shows is where the thinking has got to, so it still reads as progress while it
 * streams; opening it shows all of it. */
function Thinking({ text }: { text: string }) {
  const latest = lastLine(text);
  return (
    <details className="thinking">
      <summary>
        <span className="thinking-label">Thinking</span>
        <span className="thinking-latest">{latest}</span>
      </summary>
      <div className="model-note">{text.trim()}</div>
    </details>
  );
}

function stateOf(call: ToolCall): { mark: string; tone: string; text: string } {
  const state = call.permission?.state;
  if (state === "asking") return { mark: "?", tone: "tone-ask", text: "waiting for you" };
  if (state === "declined") return { mark: "✕", tone: "tone-bad", text: "you declined" };
  if (state === "denied") return { mark: "✕", tone: "tone-bad", text: "the policy refused" };
  if (!call.result) return { mark: "…", tone: "tone-run", text: "running" };
  const time = call.seconds !== undefined ? `${call.seconds < 1 ? call.seconds.toFixed(2) : call.seconds.toFixed(1)} s` : "";
  const who = state === "allowed" ? "you allowed" : "";
  const text = [call.result.isError ? "error" : "", who, time].filter(Boolean).join(" · ");
  return call.result.isError ? { mark: "✕", tone: "tone-bad", text } : { mark: "✓", tone: "tone-ok", text };
}

/** A to-do list update, on one line: how far along it is and the step now in progress. */
function TodoCard({ call }: { call: ToolCall }) {
  const todos = todosOf(call);
  const done = todos.filter((t) => t.status === "completed").length;
  const now = todos.find((t) => t.status === "in_progress");
  return (
    <details className="tool">
      <summary>
        <span className="tool-mark tone-ok" aria-hidden="true">
          ☰
        </span>
        <span className="tool-name">To-do</span>
        <span className="tool-arg">{now ? now.content : done === todos.length ? "all done" : ""}</span>
        <span className="tool-state">
          {done} of {todos.length} done
        </span>
      </summary>
      <div className="tool-body">
        <TodoList todos={todos} />
      </div>
    </details>
  );
}

export function ToolCard({ call, onAnswer }: { call: ToolCall; onAnswer?: Props["onAnswer"] }) {
  const state = stateOf(call);
  const diff = diffOf(call);
  const asking = call.permission?.state === "asking";
  return (
    <>
      <details
        id={`call-${call.id}`}
        className={`tool ${call.result?.isError ? "tool-error" : ""}`}
        open={Boolean(diff) || asking}
      >
        <summary>
          <span className={`tool-mark ${state.tone}`} aria-hidden="true">
            {state.mark}
          </span>
          <span className="tool-name">{call.name}</span>
          <span className="tool-arg" title={keyArgument(call)}>
            {keyArgument(call)}
          </span>
          {diff && <DiffCount diff={diff} />}
          <span className={`tool-state ${state.tone === "tone-bad" ? "status-failed" : ""}`}>{state.text}</span>
        </summary>
        <div className="tool-body">
          {call.permission && call.permission.state !== "asking" && (
            <p className="muted">
              <Ticks text={call.permission.reason} /> ({call.permission.state})
            </p>
          )}
          {call.hooks.map((hook, i) => (
            <p key={i} className="notice notice-warn">
              {hook.event} hook: {hook.message}
            </p>
          ))}
          {writeKind(call) && <p className="muted">{writeKind(call)}</p>}
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
                Result{call.result.untrusted ? " (untrusted: from a file, command, web page or server)" : ""}
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
  const always = call.permission?.rules.join(", ") ?? "";
  return (
    <div className="ask" role="group" aria-label="Permission request">
      <div className="ask-reason">
        <Ticks text={call.permission?.reason ?? ""} />
      </div>
      {onAnswer ? (
        <div className="row">
          <button className="button button-primary" onClick={() => onAnswer(call.id, "once")}>
            Allow once
          </button>
          {canAlwaysAllow(call) && (
            <button className="button" onClick={() => onAnswer(call.id, "always")} title={always}>
              Always allow <span className="mono">{always}</span>
            </button>
          )}
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
