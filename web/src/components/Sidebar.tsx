"use client";

import { ChartColumn, Check, Palette, Plus, Search } from "lucide-react";
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
  const { data } = useApi<SessionList>(hasToken ? "/api/sessions" : null, REFRESH_MS);

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
        <Link
          key={s.id}
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
      ))}

      {recent.length > 0 && <p className="sidebar-heading sidebar-recent">Recent</p>}
      {recent.map((s) => (
        <button
          key={s.id}
          className="sidebar-link sidebar-recent"
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
      ))}

      <p className="sidebar-heading">Workspace</p>
      <Link href="/evals/" className="sidebar-link" aria-current={path.startsWith("/evals") ? "page" : undefined}>
        <ChartColumn size={16} aria-hidden="true" />
        Evals
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

  const options: { id: ThemeChoice; name: string; about: string }[] = [
    { id: "system", name: "Match system", about: "Paper by day, Graphite by night" },
    ...THEMES,
  ];
  const current = options.find((o) => o.id === choice)?.name ?? "Match system";

  return (
    <div ref={box} style={{ position: "relative" }}>
      {open && (
        <div
          role="radiogroup"
          aria-label="Theme"
          className="glass"
          style={{ position: "absolute", bottom: "calc(100% + 6px)", left: 0, right: 0, padding: 6, borderRadius: 14, zIndex: 10 }}
        >
          {options.map((o) => (
            <button
              key={o.id}
              role="radio"
              aria-checked={choice === o.id}
              className="sidebar-link"
              style={{ width: "100%", border: 0, background: "transparent", font: "inherit", cursor: "pointer", textAlign: "left" }}
              onClick={() => pick(o.id)}
            >
              <span style={{ flex: 1 }}>
                <span className="sidebar-title">{o.name}</span>
                <span className="sidebar-sub">{o.about}</span>
              </span>
              {choice === o.id && <Check size={14} aria-hidden="true" />}
            </button>
          ))}
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
