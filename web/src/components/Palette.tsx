"use client";

import { Search } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { api, rememberFirstPrompt, type DemoInfo, type SessionList, type SessionStatus } from "@/lib/api";
import { shortcut, useIsMac } from "@/lib/platform";
import { chooseTheme, THEMES } from "@/lib/theme";
import { TABS } from "./inspector/Inspector";
import { useApi, useHasToken } from "./useApi";

interface Command {
  group: string;
  label: string;
  hint?: string;
  onlyWhenSearched?: boolean; // shown once something is typed
  run: () => void | Promise<void>;
}

/** Draft 07: every place and action in one searchable list. ⌘K anywhere, or the sidebar. */
export function Palette() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("zwans:palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("zwans:palette", onOpen);
    };
  }, []);

  return open ? <Dialog close={() => setOpen(false)} /> : null;
}

/** The open palette. It mounts fresh each time, so the search starts empty. */
function Dialog({ close }: { close: () => void }) {
  const mac = useIsMac();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const [problem, setProblem] = useState<string | null>(null);
  const router = useRouter();
  const path = usePathname();
  const params = useSearchParams();
  const hasToken = useHasToken();
  const { data: sessions } = useApi<SessionList>(hasToken ? "/api/sessions" : null);

  useEffect(() => {
    const restore = document.activeElement as HTMLElement | null;
    return () => restore?.focus?.();
  }, []);

  const sessionId = path.startsWith("/session") ? params.get("id") : null;

  const commands = useMemo<Command[]>(() => {
    const go = (href: string) => () => router.push(href);
    const list: Command[] = [];
    if (sessionId) {
      for (const t of TABS) {
        list.push({
          group: "Inspect this session",
          label: t.name,
          hint: t.about,
          run: go(`/session/?id=${encodeURIComponent(sessionId)}&tab=${t.id}`),
        });
      }
      list.push({ group: "Inspect this session", label: "Back to the conversation", run: go(`/session/?id=${encodeURIComponent(sessionId)}`) });
    }
    list.push(
      { group: "Go to", label: "Home: new session", hint: "Start a task in a folder", run: go("/") },
      { group: "Go to", label: "Eval runs", hint: "Every report in evals/reports", run: go("/evals/") },
      { group: "Go to", label: "Task matrix", hint: "Tasks × configs, pass counts", run: go("/evals/matrix/") },
      { group: "Go to", label: "Leaderboard", hint: "Pass rate against cost, for everything run", run: go("/evals/leaderboard/") },
      { group: "Go to", label: "Usage", hint: "Tokens and cost by day, week, month and year", run: go("/usage/") },
      { group: "Help", label: "Wtf is Zwans", hint: "What it is, what it has, its tools", run: go("/about/") },
      {
        group: "Help",
        label: "Keyboard shortcuts",
        hint: "Or press ? anywhere",
        run: () => void window.dispatchEvent(new Event("zwans:shortcuts")),
      },
    );
    for (const s of sessions?.live ?? []) {
      list.push({
        group: "Open sessions",
        label: s.title || (s.chat ? "New chat" : "New session"),
        hint: s.chat ? "Chat, no folder" : s.workspace,
        run: go(`/session/?id=${encodeURIComponent(s.id)}`),
      });
    }
    // Every saved session can be found by typing; the latest eight show before anything is.
    (sessions?.saved ?? []).filter((x) => !x.live).forEach((s, i) => {
      list.push({
        group: s.pinned ? "Pinned" : "Resume",
        label: s.title || "(no prompt)",
        hint: s.chat ? "Chat, no folder" : s.workspace,
        onlyWhenSearched: i >= 8,
        run: async () => {
          await api<SessionStatus>(`/api/sessions/${encodeURIComponent(s.id)}/open`, { method: "POST" });
          router.push(`/session/?id=${encodeURIComponent(s.id)}`);
        },
      });
    });
    list.push({
      group: "Start",
      label: "New chat",
      hint: "Talk to the model with no folder and no tools",
      run: async () => {
        const status = await api<SessionStatus>("/api/sessions", { method: "POST", body: JSON.stringify({ chat: true }) });
        router.push(`/session/?id=${encodeURIComponent(status.id)}`);
      },
    });
    list.push({
      group: "Demo",
      label: "Start the demo",
      hint: "A scripted session: real tools, no API calls",
      run: async () => {
        const [info, status] = await Promise.all([
          api<DemoInfo>("/api/demo"),
          api<SessionStatus>("/api/sessions", { method: "POST", body: JSON.stringify({ demo: true, mode: "ask" }) }),
        ]);
        if (info.prompts[0]) rememberFirstPrompt(status.id, info.prompts[0]);
        router.push(`/session/?id=${encodeURIComponent(status.id)}`);
      },
    });
    list.push({ group: "Theme", label: "Theme: match system", run: () => chooseTheme("system") });
    for (const t of THEMES) list.push({ group: "Theme", label: `Theme: ${t.name}`, hint: t.about, run: () => chooseTheme(t.id) });
    return list;
  }, [router, sessionId, sessions]);

  const shown = useMemo(() => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    return commands.filter((c) => {
      if (c.onlyWhenSearched && !words.length) return false;
      const text = `${c.group} ${c.label} ${c.hint ?? ""}`.toLowerCase();
      return words.every((w) => text.includes(w));
    });
  }, [commands, query]);

  const run = async (command: Command | undefined) => {
    if (!command) return;
    try {
      await command.run();
      close();
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    }
  };

  let lastGroup = "";
  return (
    <div className="palette-backdrop" data-palette-open onMouseDown={() => close()}>
      <div
        className="palette glass"
        role="dialog"
        aria-modal="true"
        aria-label="Search and commands"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="palette-search">
          <Search size={16} aria-hidden="true" />
          <input
            autoFocus
            value={query}
            placeholder="Search sessions, views and commands"
            aria-label="Search"
            aria-controls="palette-list"
            aria-activedescendant={shown[active] ? `palette-${active}` : undefined}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setActive((a) => Math.min(a + 1, shown.length - 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setActive((a) => Math.max(a - 1, 0));
              } else if (e.key === "Enter") {
                e.preventDefault();
                void run(shown[active]);
              } else if (e.key === "Escape") {
                e.preventDefault();
                close();
              }
            }}
          />
          <span className="kbd">esc</span>
        </div>
        {problem && <div className="notice notice-bad" style={{ margin: 8 }}>{problem}</div>}
        <ul id="palette-list" role="listbox" className="palette-list">
          {shown.length === 0 && <li className="muted palette-empty">Nothing matches.</li>}
          {shown.map((c, i) => {
            const heading = c.group !== lastGroup ? c.group : null;
            lastGroup = c.group;
            return (
              <li key={`${c.group}-${c.label}-${i}`} role="presentation">
                {heading && <div className="palette-group">{heading}</div>}
                <div
                  id={`palette-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className="palette-item"
                  onMouseMove={() => setActive(i)}
                  onClick={() => void run(c)}
                >
                  <span className="palette-label">{c.label}</span>
                  {c.hint && <span className="palette-hint">{c.hint}</span>}
                </div>
              </li>
            );
          })}
        </ul>
        <div className="palette-foot">
          <span>
            <span className="kbd">↑↓</span> move
          </span>
          <span>
            <span className="kbd">↵</span> run
          </span>
          <span>
            <span className="kbd">{shortcut(mac, "K")}</span> anywhere
          </span>
        </div>
      </div>
    </div>
  );
}
