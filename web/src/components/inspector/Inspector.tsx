"use client";

import { ChevronLeft } from "lucide-react";
import { useEffect } from "react";
import type { SessionStatus } from "@/lib/api";
import type { UnderTheHood } from "@/lib/calls";
import type { RawEvent } from "@/lib/events";
import { CompactionTab } from "./CompactionTab";
import { ContextMap } from "./ContextMap";
import { CostCache } from "./CostCache";
import { RawRequest } from "./RawRequest";
import { Waterfall } from "./Waterfall";

export const TABS = [
  { id: "context", label: "Context", name: "Context map", about: "What the request held, and what came from the cache" },
  { id: "calls", label: "Calls", name: "Calls waterfall", about: "Every model call in a turn, on a timeline" },
  { id: "request", label: "Request", name: "Raw request", about: "The last request, exactly as the API got it" },
  { id: "cost", label: "Cost", name: "Cost and cache", about: "Where the money went, and what the cache saved" },
  { id: "compaction", label: "Compaction", name: "Compaction", about: "When the conversation was summarized, and into what" },
] as const;

export type InspectorTab = (typeof TABS)[number]["id"];

export const isTab = (value: string | null): value is InspectorTab => TABS.some((t) => t.id === value);

export interface InspectorProps {
  sessionId: string;
  status: SessionStatus | null;
  events: RawEvent[];
  data: UnderTheHood;
}

interface Props extends InspectorProps {
  tab: InspectorTab;
  onTab: (tab: InspectorTab) => void;
  onClose: () => void;
}

/** The full-screen inspector: the session's machinery, one view per tab. */
export function Inspector({ tab, onTab, onClose, ...props }: Props) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !document.querySelector("[data-palette-open]")) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="inspect">
      <header className="session-head glass">
        <button className="button button-quiet inspect-back" onClick={onClose} title="Back to the conversation (Esc)">
          <ChevronLeft size={16} aria-hidden="true" />
          <span>{props.status?.title || "Session"}</span>
        </button>
        <nav className="segmented" aria-label="Inspector views">
          {TABS.map((t) => (
            <button key={t.id} aria-current={tab === t.id ? "page" : undefined} onClick={() => onTab(t.id)} title={t.about}>
              {t.label}
            </button>
          ))}
        </nav>
        <span style={{ flex: 1 }} />
        {props.status?.running && <span className="pill pulse">Live</span>}
      </header>
      <div className="inspect-body">
        {tab === "context" && <ContextMap {...props} />}
        {tab === "calls" && <Waterfall {...props} />}
        {tab === "request" && <RawRequest {...props} />}
        {tab === "cost" && <CostCache {...props} />}
        {tab === "compaction" && <CompactionTab {...props} />}
      </div>
    </div>
  );
}

/** A tab with nothing to show yet. */
export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="panel glass muted">{children}</div>;
}
