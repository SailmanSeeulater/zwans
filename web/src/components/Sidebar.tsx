"use client";

import { ChartColumn, Check, Command, Gauge, Monitor, Palette, Pencil, Pin, PinOff, Plus, Search, Settings, Trash2, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { api, type SavedSession, type SessionList, type SessionStatus } from "@/lib/api";
import { shortcut, useIsMac } from "@/lib/platform";
import { arrange } from "@/lib/sessions";
import { chooseTheme, readChoice, THEMES, type ThemeChoice } from "@/lib/theme";
import { useApi, useHasToken } from "./useApi";
import { StatusDot } from "./Working";
import { livenessOf, type Liveness } from "@/lib/working";

const REFRESH_MS = 3_000;
const RECENT = 6;

/** A session as one sidebar row shows it, open or saved. */
interface Row {
  id: string;
  title: string;
  sub: string;
  live: boolean;
  pinned: boolean;
  named: boolean;
  waiting: number;
  state: Liveness | null; // null for a session that isn't open
}

/** The left column: new session, the pinned, open and recent sessions with a search box over
 * all of them, evals, and the theme. */
export function Sidebar() {
  const path = usePathname();
  const currentId = useSearchParams().get("id");
  const router = useRouter();
  const hasToken = useHasToken();
  const mac = useIsMac();
  const { data, reload } = useApi<SessionList>(hasToken ? "/api/sessions" : null, REFRESH_MS);
  const [asking, setAsking] = useState<string | null>(null); // the session a delete is being confirmed for
  const [editing, setEditing] = useState<string | null>(null); // the session being renamed
  const [query, setQuery] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const shown = arrange(data, query, RECENT);
  const statusOf = new Map((data?.live ?? []).map((s) => [s.id, s]));
  const fromStatus = (s: SessionStatus): Row => ({
    id: s.id,
    title: s.title || (s.chat ? "New chat" : "New session"),
    sub: `${s.running ? (s.waiting_for.length ? "waiting for you" : "working") : "idle"} · ${placeOf(s)}`,
    live: true,
    pinned: Boolean(s.pinned),
    named: false,
    waiting: s.waiting_for.length,
    state: livenessOf(s),
  });
  const fromSaved = (s: SavedSession): Row => {
    const status = statusOf.get(s.id);
    const row = status ? fromStatus(status) : null;
    return {
      id: s.id,
      title: s.title || "(no prompt)",
      sub: row?.sub ?? `${placeOf(s)} · ${s.turns} ${s.turns === 1 ? "turn" : "turns"}`,
      live: Boolean(status),
      pinned: s.pinned,
      named: s.named,
      waiting: row?.waiting ?? 0,
      state: row?.state ?? null,
    };
  };

  const resume = async (id: string) => {
    try {
      await api<SessionStatus>(`/api/sessions/${encodeURIComponent(id)}/open`, { method: "POST" });
    } catch {
      // The session's page tries once more and says why it can't be resumed.
    }
    router.push(`/session/?id=${encodeURIComponent(id)}`);
  };

  const failed = (what: string) => (error: unknown) =>
    setProblem(`Couldn't ${what}: ${error instanceof Error ? error.message : String(error)}`);

  const remove = async (id: string) => {
    setAsking(null);
    try {
      await api<void>(`/api/sessions/${encodeURIComponent(id)}/saved`, { method: "DELETE" });
      setProblem(null);
      if (currentId === id && path.startsWith("/session")) router.push("/");
    } catch (error) {
      failed("delete it")(error);
    }
    reload();
  };

  const mark = async (id: string, change: { name?: string; pinned?: boolean }, what: string) => {
    try {
      await api<void>(`/api/sessions/${encodeURIComponent(id)}/saved`, { method: "PATCH", body: JSON.stringify(change) });
      setProblem(null);
    } catch (error) {
      failed(what)(error);
    }
    reload();
  };

  const row = (r: Row, extra = "") => {
    const current = path.startsWith("/session") && currentId === r.id;
    const body = (
      <span style={{ minWidth: 0, flex: 1 }}>
        <span className="sidebar-title">
          {r.state && <StatusDot state={r.state} />}
          {r.title}
        </span>
        <span className="sidebar-sub">{r.sub}</span>
      </span>
    );
    return (
      <div key={r.id} className={`sidebar-row ${extra}`} data-asking={asking === r.id || undefined}>
        {editing === r.id ? (
          <RenameField
            title={r.named ? r.title : ""}
            placeholder={r.title}
            onDone={(name) => {
              setEditing(null);
              if (name !== null) void mark(r.id, { name }, "rename it");
            }}
          />
        ) : r.live ? (
          <Link
            href={`/session/?id=${encodeURIComponent(r.id)}`}
            className="sidebar-link"
            aria-current={current ? "page" : undefined}
            onDoubleClick={(e) => {
              e.preventDefault();
              setEditing(r.id);
            }}
          >
            {body}
            {r.waiting > 0 && (
              <span className="sidebar-badge" aria-label={`${r.waiting} waiting`}>
                {r.waiting}
              </span>
            )}
          </Link>
        ) : (
          <button
            className="sidebar-link"
            style={{ border: 0, background: "transparent", font: "inherit", cursor: "pointer", textAlign: "left" }}
            onClick={() => void resume(r.id)}
            onDoubleClick={() => setEditing(r.id)}
            title="Resume this session"
          >
            {body}
          </button>
        )}
        {editing !== r.id && asking !== r.id && (
          <span className="sidebar-actions">
            <button
              className="sidebar-action"
              onClick={() => void mark(r.id, { pinned: !r.pinned }, r.pinned ? "unpin it" : "pin it")}
              aria-label={`${r.pinned ? "Unpin" : "Pin"} ${r.title}`}
              aria-pressed={r.pinned}
              title={r.pinned ? "Unpin" : "Pin to the top"}
            >
              {r.pinned ? <PinOff size={13} aria-hidden="true" /> : <Pin size={13} aria-hidden="true" />}
            </button>
            <button
              className="sidebar-action"
              onClick={() => setEditing(r.id)}
              aria-label={`Rename ${r.title}`}
              title="Rename"
            >
              <Pencil size={13} aria-hidden="true" />
            </button>
            <button
              className="sidebar-action sidebar-delete"
              onClick={() => setAsking(r.id)}
              aria-label={`Delete ${r.title}`}
              title="Delete this session. The files it changed stay."
            >
              <Trash2 size={13} aria-hidden="true" />
            </button>
          </span>
        )}
        {asking === r.id && (
          <span className="sidebar-confirm" role="group" aria-label={`Delete ${r.title}?`}>
            <button className="button button-danger" onClick={() => void remove(r.id)} autoFocus>
              Delete
            </button>
            <button className="button" onClick={() => setAsking(null)}>
              Keep
            </button>
          </span>
        )}
      </div>
    );
  };

  const anySaved = (data?.saved.length ?? 0) > 0;

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
        <Command size={16} aria-hidden="true" />
        Commands
        <span className="kbd" style={{ marginLeft: "auto" }}>
          {shortcut(mac, "K")}
        </span>
      </button>

      {anySaved && (
        <label className="sidebar-search">
          <Search size={14} aria-hidden="true" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") setQuery("");
            }}
            placeholder="Find a session"
            aria-label="Find a session by its title, folder or model"
          />
        </label>
      )}

      {shown.found ? (
        <>
          <p className="sidebar-heading">
            {shown.found.length ? `${shown.found.length} found` : "No session matches"}
          </p>
          {shown.found.map((s) => row(fromSaved(s)))}
        </>
      ) : (
        <>
          {shown.pinned.length > 0 && <p className="sidebar-heading">Pinned</p>}
          {shown.pinned.map((s) => row(fromSaved(s)))}

          {shown.open.length > 0 && <p className="sidebar-heading">Open</p>}
          {shown.open.map((s) => row(fromStatus(s)))}

          {shown.recent.length > 0 && <p className="sidebar-heading sidebar-recent">Recent</p>}
          {shown.recent.map((s) => row(fromSaved(s), "sidebar-recent"))}
        </>
      )}
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
      <Link href="/settings/" className="sidebar-link" aria-current={path.startsWith("/settings") ? "page" : undefined}>
        <Settings size={16} aria-hidden="true" />
        Settings
      </Link>

      <div className="sidebar-spacer" />
      <ThemeMenu />
    </nav>
  );
}

/** Where a row's name is typed. Enter or leaving the field keeps it, Escape doesn't; an empty
 * name gives back the title from the first prompt. Calls onDone with the name, or null. */
function RenameField({ title, placeholder, onDone }: { title: string; placeholder: string; onDone: (name: string | null) => void }) {
  const [draft, setDraft] = useState(title);
  const done = useRef(false);
  const finish = (name: string | null) => {
    if (done.current) return; // Enter, then the blur it causes
    done.current = true;
    onDone(name !== null && name.trim() === title ? null : name);
  };
  return (
    <input
      className="sidebar-rename"
      value={draft}
      placeholder={placeholder}
      maxLength={80}
      autoFocus
      onFocus={(e) => e.target.select()}
      onChange={(e) => setDraft(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") finish(draft);
        if (e.key === "Escape") finish(null);
      }}
      onBlur={() => finish(draft)}
      aria-label="Session name. Leave it empty to use the first prompt."
    />
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
