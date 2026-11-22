"use client";

import { ArrowDown, Check, Copy, Keyboard, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { shortcut, useIsMac } from "@/lib/platform";

/** Copies some text, and says so for a moment. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1400);
    return () => clearTimeout(timer);
  }, [copied]);
  return (
    <button
      className="msg-action"
      data-done={copied || undefined}
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => setCopied(true));
      }}
      aria-label={copied ? "Copied" : label}
      title={copied ? "Copied" : label}
    >
      {copied ? <Check size={13} aria-hidden="true" /> : <Copy size={13} aria-hidden="true" />}
    </button>
  );
}

export function ActionButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button className="msg-action" onClick={onClick} aria-label={label} title={label}>
      {children}
    </button>
  );
}

/** Floats above the composer once you've scrolled up, and brings you back down. A dot
 * says there's something new since. */
export function JumpToLatest({ shown, fresh, onJump }: { shown: boolean; fresh: boolean; onJump: () => void }) {
  return (
    <button className="jump-latest" data-shown={shown || undefined} onClick={onJump} tabIndex={shown ? 0 : -1} aria-hidden={!shown}>
      {fresh && <span className="jump-latest-dot" aria-hidden="true" />}
      <ArrowDown size={13} aria-hidden="true" />
      {fresh ? "New below" : "Jump to latest"}
    </button>
  );
}

const SHORTCUTS: [string, string][] = [
  ["K", "Search sessions, views and commands"],
  ["Enter", "Send (Shift+Enter for a new line)"],
  ["Esc", "Stop the turn that's running"],
  ["/", "Focus the message box"],
  ["J", "Jump to the latest message"],
  ["\\", "Show or hide the side pane"],
  ["?", "Show these shortcuts"],
];
const WITH_MOD = new Set(["K", "\\"]);

/** The keyboard shortcuts, opened with "?" anywhere outside a text field. */
export function ShortcutHelp() {
  const mac = useIsMac();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && open) setOpen(false);
      if (event.key !== "?" || typing(event)) return;
      event.preventDefault();
      setOpen((now) => !now);
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("zwans:shortcuts", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("zwans:shortcuts", onOpen);
    };
  }, [open]);
  if (!open) return null;
  return (
    <div className="shortcuts-backdrop" onClick={() => setOpen(false)}>
      <div className="shortcuts glass" role="dialog" aria-label="Keyboard shortcuts" onClick={(e) => e.stopPropagation()}>
        <div className="shortcuts-head">
          <Keyboard size={16} aria-hidden="true" />
          <strong>Keyboard shortcuts</strong>
          <span style={{ flex: 1 }} />
          <button className="msg-action" onClick={() => setOpen(false)} aria-label="Close">
            <X size={14} aria-hidden="true" />
          </button>
        </div>
        <dl>
          {SHORTCUTS.map(([key, what]) => (
            <div key={key} className="shortcut-row">
              <dt>
                <span className="kbd">{WITH_MOD.has(key) ? shortcut(mac, key) : key}</span>
              </dt>
              <dd>{what}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

/** Whether a key press is typing into something, which shortcuts leave alone. */
export function typing(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}
