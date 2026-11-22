"use client";

import { ChartColumn, Check, Gauge, Monitor, Palette, Plus, Search, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, type SessionList, type SessionStatus } from "@/lib/api";
import { shortcut, useIsMac } from "@/lib/platform";
import { chooseTheme, readChoice, THEMES, type ThemeChoice } from "@/lib/theme";
import { useApi, useHasToken } from "./useApi";

const REFRESH_MS = 3_000;
const RECENT = 6;

/** The left column: new session, the open and recent sessions, evals, and the theme. */
export function Sidebar() {
  const path = usePathname();
  const currentId = useSearchParams().get("id");
  const router = useRouter();
  const hasToken = useHasToken();
  const mac = useIsMac();
  const { data, reload } = useApi<SessionList>(hasToken ? "/api/sessions" : null, REFRESH_MS);
  const [asking, setAsking] = useState<string | null>(null); // the session a delete is being confirmed for
  const [problem, setProblem] = useState<string | null>(null);

  const live = data?.live ?? [];
  const recent = (data?.saved ?? []).filter((s) => !s.live).slice(0, RECENT);

  const resume = async (id: string) => {
    try {
      await api<SessionStatus>(`/api/sessions/${encodeURIComponent(id)}/open`, { method: "POST" });
    } catch {
      // The session's page tries once more and says why it can't be resumed.
    }
    router.push(`/session/?id=${encodeURIComponent(id)}`);
  };

  const remove = async (id: string) => {
    setAsking(null);
    try {
      await api<void>(`/api/sessions/${encodeURIComponent(id)}/saved`, { method: "DELETE" });
      setProblem(null);
      if (currentId === id && path.startsWith("/session")) router.push("/");
    } catch (error) {
      setProblem(`Couldn't delete it: ${error instanceof Error ? error.message : String(error)}`);
    }
    reload();
  };
  // The row's own delete button, or the question it turns into.
  const deleting = (id: string, title: string) =>
    asking === id ? (
      <span className="sidebar-confirm" role="group" aria-label={`Delete ${title}?`}>
        <button className="button button-danger" onClick={() => void remove(id)} autoFocus>
          Delete
        </button>
        <button className="button" onClick={() => setAsking(null)}>
          Keep
        </button>
      </span>
    ) : (
      <button
        className="sidebar-delete"
        onClick={() => setAsking(id)}
        aria-label={`Delete ${title}`}
        title="Delete this session. The files it changed stay."
      >
        <Trash2 size={13} aria-hidden="true" />
      </button>
    );

  return (
    <nav className="sidebar glass" aria-label="Zwans">
      <div className="sidebar-brand">Zwans</div>
      <Link href="/" className="sidebar-link" aria-current={path === "/" ? "page" : undefined}>
        <Plus size={16} aria-hidden="true" />
        New session
      </Link>
      <button
        className="sidebar-link button-quiet"
        style={{ border: 0, background: "transparent", font: "inherit", cursor: "pointer", textAlign: "left" }}
        onClick={() => window.dispatchEvent(new Event("zwans:palette"))}
        title="Search sessions, views and commands"
      >
        <Search size={16} aria-hidden="true" />
        Search
        <span className="kbd" style={{ marginLeft: "auto" }}>
          {shortcut(mac, "K")}
        </span>
      </button>

      {live.length > 0 && <p className="sidebar-heading">Open</p>}
      {live.map((s) => (
        <div key={s.id} className="sidebar-row" data-asking={asking === s.id || undefined}>
        <Link
          href={`/session/?id=${encodeURIComponent(s.id)}`}
          className="sidebar-link"
          aria-current={path.startsWith("/session") && currentId === s.id ? "page" : undefined}
        >
          <span style={{ minWidth: 0, flex: 1 }}>
            <span className="sidebar-title">{s.title || (s.chat ? "New chat" : "New session")}</span>
            <span className="sidebar-sub">
              {s.running ? (s.waiting_for.length ? "waiting for you" : "working") : "idle"} · {placeOf(s)}
            </span>
          </span>
          {s.waiting_for.length > 0 && (
            <span className="sidebar-badge" aria-label={`${s.waiting_for.length} waiting`}>
              {s.waiting_for.length}
            </span>
          )}
        </Link>
        {deleting(s.id, s.title || (s.chat ? "New chat" : "New session"))}
        </div>
      ))}

      {recent.length > 0 && <p className="sidebar-heading sidebar-recent">Recent</p>}
      {recent.map((s) => (
        <div key={s.id} className="sidebar-row sidebar-recent" data-asking={asking === s.id || undefined}>
        <button
          className="sidebar-link"
          style={{ border: 0, background: "transparent", font: "inherit", cursor: "pointer", textAlign: "left" }}
          onClick={() => void resume(s.id)}
          title="Resume this session"
        >
          <span style={{ minWidth: 0, flex: 1 }}>
            <span className="sidebar-title">{s.title || "(no prompt)"}</span>
            <span className="sidebar-sub">
              {placeOf(s)} · {s.turns} {s.turns === 1 ? "turn" : "turns"}
            </span>
          </span>
        </button>
        {deleting(s.id, s.title || "(no prompt)")}
        </div>
      ))}
      {problem && (
        <p className="sidebar-problem status-failed" role="alert">
          {problem}
        </p>
      )}

      <p className="sidebar-heading">Workspace</p>
      <Link href="/room/" className="sidebar-link" aria-current={path.startsWith("/room") ? "page" : undefined}>
        <Users size={16} aria-hidden="true" />
        Rooms
      </Link>
      <Link href="/evals/" className="sidebar-link" aria-current={path.startsWith("/evals") ? "page" : undefined}>
        <ChartColumn size={16} aria-hidden="true" />
        Evals
      </Link>
      <Link href="/usage/" className="sidebar-link" aria-current={path.startsWith("/usage") ? "page" : undefined}>
        <Gauge size={16} aria-hidden="true" />
        Usage
      </Link>

      <div className="sidebar-spacer" />
      <ThemeMenu />
    </nav>
  );
}

/** Where a session works: its folder's name, or "chat" for one with no folder. */
function placeOf(session: { workspace: string; chat?: boolean }): string {
  if (session.chat) return "chat";
  return session.workspace.split("/").filter(Boolean).at(-1) ?? session.workspace;
}

function ThemeMenu() {
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<ThemeChoice>("system");
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // localStorage only exists in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChoice(readChoice());
  }, []);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !box.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const pick = (next: ThemeChoice) => {
    chooseTheme(next);
    setChoice(next);
  };

  const current = THEMES.find((t) => t.id === choice)?.name ?? "Match system";
  // One row for a theme: its own page and accent colours as a dot, then its name.
  const option = (id: ThemeChoice, name: string, about: string) => (
    <button
      key={id}
      role="radio"
      aria-checked={choice === id}
      className="theme-option"
      title={about}
      onClick={() => pick(id)}
    >
      {id === "system" ? (
        <Monitor size={16} aria-hidden="true" />
      ) : (
        <span className="theme-swatch" data-theme={id} aria-hidden="true" />
      )}
      <span className="theme-name">{name}</span>
      {choice === id && <Check size={14} aria-hidden="true" />}
    </button>
  );

  return (
    <div ref={box} style={{ position: "relative" }}>
      {open && (
        <div role="radiogroup" aria-label="Theme" className="theme-menu glass">
          {option("system", "Match system", "Paper by day, Graphite by night")}
          <p className="theme-heading">Light</p>
          {THEMES.filter((t) => !t.dark).map((t) => option(t.id, t.name, t.about))}
          <p className="theme-heading">Dark</p>
          {THEMES.filter((t) => t.dark).map((t) => option(t.id, t.name, t.about))}
        </div>
      )}
      <button
        className="sidebar-link"
        style={{ width: "100%", border: 0, background: "transparent", font: "inherit", cursor: "pointer", textAlign: "left", color: "var(--ink-2)" }}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <Palette size={16} aria-hidden="true" />
        Theme: {current}
      </button>
    </div>
  );
}
