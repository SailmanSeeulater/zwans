"use client";

import { ChevronDown, Cpu } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, type ModelListing, type SessionStatus } from "@/lib/api";

interface Props {
  sessionId: string;
  model: string;
  /** While a turn runs, or for the demo's scripted model. */
  disabled: boolean;
  onSwitched: (status: SessionStatus) => void;
  onError: (message: string) => void;
}

/** The session's model, and a menu to switch it: Claude, models on local servers, or any
 * provider's model typed as provider/model. */
export function ModelPicker({ sessionId, model, disabled, onSwitched, onError }: Props) {
  const [open, setOpen] = useState(false);
  const [listings, setListings] = useState<ModelListing[] | null>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [alignRight, setAlignRight] = useState(false); // so the menu stays on screen
  const box = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    let current = true;
    api<{ providers: ModelListing[] }>("/api/models")
      .then((found) => current && setListings(found.providers))
      .catch((error: unknown) => current && onError(`Couldn't list the models: ${messageOf(error)}`));
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", escape);
    return () => {
      current = false;
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [open, onError]);

  const choose = async (name: string) => {
    if (!name.trim() || name === model) return setOpen(false);
    setBusy(true);
    try {
      const status = await api<SessionStatus>(`/api/sessions/${encodeURIComponent(sessionId)}/model`, {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      onSwitched(status);
      setTyped("");
      setOpen(false);
    } catch (error) {
      onError(`Couldn't switch to ${name.trim()}: ${messageOf(error)}`);
    } finally {
      setBusy(false);
    }
  };

  const listMore = async (provider: string) => {
    try {
      const found = await api<{ providers: ModelListing[] }>(`/api/models?provider=${encodeURIComponent(provider)}`);
      const fresh = found.providers[0];
      if (fresh) setListings((previous) => previous?.map((l) => (l.provider === provider ? fresh : l)) ?? null);
    } catch (error) {
      onError(`Couldn't list ${provider}'s models: ${messageOf(error)}`);
    }
  };

  const ready = listings?.filter((l) => l.ready) ?? [];
  const notReady = listings?.filter((l) => !l.ready) ?? [];

  return (
    <div className="model-picker" ref={box}>
      <button
        className="pill pill-quiet model-button mono"
        onClick={(e) => {
          const left = e.currentTarget.getBoundingClientRect().left;
          setAlignRight(left + MENU_WIDTH + 16 > window.innerWidth);
          setOpen(!open);
        }}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={`Model: ${model}. Switch it`}
        title={disabled ? "Switch models between turns" : "Switch the model"}
      >
        <Cpu size={12} aria-hidden="true" />
        {model}
        <ChevronDown size={12} aria-hidden="true" />
      </button>
      {open && (
        <div className={`model-menu glass ${alignRight ? "model-menu-right" : ""}`} role="dialog" aria-label="Choose a model">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void choose(typed);
            }}
          >
            <input
              className="input mono"
              autoFocus
              placeholder="provider/model, as ollama/qwen3:8b"
              aria-label="Model name"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              disabled={busy}
            />
          </form>
          {listings === null && <p className="muted small">Asking the providers…</p>}
          {ready.map((listing) => (
            <div key={listing.provider} className="model-group">
              <div className="label">
                {listing.provider} <span className="muted">· {listing.about}</span>
              </div>
              {listing.models.map((name) => (
                <button
                  key={name}
                  className={`model-option mono ${name === model ? "model-current" : ""}`}
                  onClick={() => void choose(name)}
                  disabled={busy}
                >
                  {name}
                </button>
              ))}
              {listing.models.length === 0 && !listing.local && (
                <button className="button button-quiet small" onClick={() => void listMore(listing.provider)}>
                  List its models
                </button>
              )}
            </div>
          ))}
          {notReady.length > 0 && (
            <details className="model-group">
              <summary className="muted small">Not set up ({notReady.length})</summary>
              {notReady.map((listing) => (
                <p key={listing.provider} className="muted small">
                  <span className="mono">{listing.provider}</span>: {listing.note}
                </p>
              ))}
            </details>
          )}
        </div>
      )}
    </div>
  );
}

const MENU_WIDTH = 380; // .model-menu's width in globals.css

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
