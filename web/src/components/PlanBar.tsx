"use client";

import { ListChecks, Play, X } from "lucide-react";

interface Props {
  running: boolean;
  /** A plan was written since plan mode went on, so there's something to approve. */
  planned: boolean;
  /** The socket is open and the session can take a message. */
  ready: boolean;
  onGo: () => void;
  onLeave: () => void;
}

/**
 * Above the composer while plan mode is on: what it means, and once a plan is written, the
 * buttons that approve it or leave without it.
 */
export function PlanBar({ running, planned, ready, onGo, onLeave }: Props) {
  return (
    <div className="plan-bar" role="status" aria-label="Plan mode">
      <ListChecks size={15} aria-hidden="true" />
      <span className="plan-bar-text">
        <strong>Plan mode.</strong>{" "}
        <span className="muted">
          {running
            ? "Zwans can look but not change anything."
            : planned
              ? "Nothing has changed. Carry out the plan, or reply to change it."
              : "Describe the task, and Zwans replies with a plan before changing anything."}
        </span>
      </span>
      {!running && (
        <span className="plan-bar-actions">
          <button className="button button-quiet button-small" onClick={onLeave} disabled={!ready}>
            <X size={12} aria-hidden="true" /> Leave
          </button>
          {planned && (
            <button className="button button-primary button-small" onClick={onGo} disabled={!ready}>
              <Play size={12} aria-hidden="true" /> Carry out the plan
            </button>
          )}
        </span>
      )}
    </div>
  );
}
