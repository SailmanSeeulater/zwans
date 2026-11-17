"use client";

import { Copy, RefreshCw } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, type LastRequest } from "@/lib/api";
import { contextTotal } from "@/lib/calls";
import { tokens } from "@/lib/format";
import { Empty, type InspectorProps } from "./Inspector";

type Part = "all" | "system" | "tools" | "messages" | "settings";

const SETTINGS = (key: string) => !["system", "tools", "messages"].includes(key);

/** Draft 11: the request body Zwans last sent, as JSON, with the cache breakpoints marked. */
export function RawRequest({ sessionId, data }: InspectorProps) {
  const [request, setRequest] = useState<Record<string, unknown> | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [part, setPart] = useState<Part>("all");
  const [copied, setCopied] = useState(false);
  const [version, setVersion] = useState(0);
  const callCount = data.calls.length;

  useEffect(() => {
    let stale = false;
    api<LastRequest>(`/api/sessions/${encodeURIComponent(sessionId)}/request`)
      .then((r) => {
        if (!stale) {
          setRequest(r.request);
          setProblem(null);
        }
      })
      .catch((err: unknown) => {
        if (!stale) setProblem(err instanceof Error ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [sessionId, callCount, version]); // a new call means a new request

  const shown = useMemo(() => {
    if (!request) return null;
    if (part === "all") return request;
    if (part === "settings") return Object.fromEntries(Object.entries(request).filter(([k]) => SETTINGS(k)));
    return { [part]: request[part] };
  }, [request, part]);
  const lines = useMemo(() => (shown ? JSON.stringify(shown, null, 2).split("\n") : []), [shown]);

  if (problem) return <div className="notice notice-bad">{problem}</div>;
  if (!request) return <Empty>No request yet. This shows the last one Zwans sent, once there is one.</Empty>;

  const messages = Array.isArray(request.messages) ? request.messages : [];
  const tools = Array.isArray(request.tools) ? (request.tools as { name?: string }[]) : [];
  const last = data.calls.at(-1);
  const isSummary = last?.purpose === "summary";
  const parts: { id: Part; name: string; tok: string; note: string }[] = [
    { id: "system", name: "System prompt", tok: last ? tokens(last.context.system) : "", note: "Zwans's instructions" },
    {
      id: "tools",
      name: `${tools.length} tools`,
      tok: last ? tokens(last.context.tools) : "",
      note: tools.map((t) => t.name).join(", ") || "none",
    },
    {
      id: "messages",
      name: `${messages.length} messages`,
      tok: last ? tokens(last.context.messages + last.context.tool_results) : "",
      note: "the conversation so far, tool results included",
    },
    {
      id: "settings",
      name: "Settings",
      tok: "",
      note: Object.keys(request).filter(SETTINGS).join(", "),
    },
  ];

  const copy = async () => {
    await navigator.clipboard.writeText(JSON.stringify(request, null, 2));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="inspect-grid inspect-grid-left">
      <aside className="panel glass inspect-side">
        <p className="muted small">
          Call {last?.n ?? "–"} of {callCount}
          {isSummary ? ", the summary request for a compaction" : ""}
          {last ? ` · ${tokens(contextTotal(last.context))} tokens` : ""}
        </p>
        <h1 className="mono" style={{ fontSize: 15 }}>
          POST /v1/messages
        </h1>
        <div className="part-list">
          <button aria-current={part === "all" ? "page" : undefined} onClick={() => setPart("all")}>
            <span>Everything</span>
          </button>
          {parts.map((p) => (
            <button key={p.id} aria-current={part === p.id ? "page" : undefined} onClick={() => setPart(p.id)}>
              <span className="row" style={{ justifyContent: "space-between" }}>
                <span>{p.name}</span>
                <span className="mono muted">{p.tok}</span>
              </span>
              <span className="muted small part-note">{p.note}</span>
            </button>
          ))}
        </div>
        <div className="row">
          <button className="button" onClick={() => void copy()}>
            <Copy size={14} aria-hidden="true" />
            {copied ? "Copied" : "Copy as JSON"}
          </button>
          <button className="button button-quiet" onClick={() => setVersion((v) => v + 1)} title="Load it again">
            <RefreshCw size={14} aria-hidden="true" />
          </button>
        </div>
        <p className="muted small">
          What Zwans sent, as the API got it. The API key travels in a header, so it is never part of this.
        </p>
      </aside>
      <section className="panel glass code-panel">
        <div className="row small muted" style={{ marginBottom: 8 }}>
          <span className="breakpoint-mark" /> Cache breakpoint: the cache covers everything up to here
        </div>
        <ol className="code-lines">
          {lines.map((line, i) => (
            <li key={i} className={line.includes('"cache_control"') ? "breakpoint" : undefined}>
              <code>{line}</code>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
