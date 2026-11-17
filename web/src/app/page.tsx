"use client";

import { FolderOpen, Play, ScrollText } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { TokenMissing, useApi, useHasToken } from "@/components/useApi";
import {
  api,
  rememberFirstPrompt,
  type DemoInfo,
  type Mode,
  type Report,
  type RunListing,
  type SessionList,
  type SessionStatus,
} from "@/lib/api";

const MODES: { id: Mode; label: string; about: string }[] = [
  { id: "read-only", label: "Read-only", about: "Reads and searches; changes nothing" },
  { id: "ask", label: "Ask", about: "Asks before each edit or command" },
  { id: "auto", label: "Auto", about: "Edits and local commands run without asking" },
];

/** Draft 19: start a task, or watch the demo with no key at all. */
export default function HomePage() {
  const hasToken = useHasToken();
  const router = useRouter();
  const { data: sessions } = useApi<SessionList>(hasToken ? "/api/sessions" : null);
  const { data: demo } = useApi<DemoInfo>(hasToken ? "/api/demo" : null);
  const { data: runs } = useApi<RunListing[]>(hasToken ? "/api/evals" : null);
  const [task, setTask] = useState("");
  const [workspace, setWorkspace] = useState("");
  const [mode, setMode] = useState<Mode>("ask");
  const [busy, setBusy] = useState<"start" | "demo" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [canPick, setCanPick] = useState(false);

  useEffect(() => {
    // Only the desktop app can open a folder dialog, and only the browser can tell.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCanPick(Boolean(window.zwansDesktop));
  }, []);

  // A failed attempt from the latest run that had one: a real transcript to read.
  const failedRun = useMemo(() => [...(runs ?? [])].reverse().find((r) => r.summary.passed < r.summary.attempts), [runs]);
  const { data: failedReport } = useApi<Report>(failedRun ? `/api/evals/${encodeURIComponent(failedRun.name)}` : null);
  const failed = failedReport?.attempts.find((a) => a.status === "failed" && a.transcript);

  const folders = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of sessions?.saved ?? []) {
      if (s.workspace.includes("zwans-demo-") || seen.has(s.workspace)) continue;
      seen.set(s.workspace, s.updated_at);
    }
    return [...seen].slice(0, 5);
  }, [sessions]);

  const go = (id: string) => router.push(`/session/?id=${encodeURIComponent(id)}`);

  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy("start");
    setProblem(null);
    try {
      const status = await api<SessionStatus>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ workspace, mode }),
      });
      if (task.trim()) rememberFirstPrompt(status.id, task.trim());
      go(status.id);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
      setBusy(null);
    }
  };

  const startDemo = async () => {
    setBusy("demo");
    setProblem(null);
    try {
      const status = await api<SessionStatus>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ demo: true, mode: "ask" }),
      });
      if (demo?.prompts[0]) rememberFirstPrompt(status.id, demo.prompts[0]);
      go(status.id);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
      setBusy(null);
    }
  };

  if (hasToken === false) {
    return (
      <main className="page">
        <h1>Zwans</h1>
        <TokenMissing />
      </main>
    );
  }

  return (
    <main className="page home">
      {demo && !demo.has_credential && (
        <div className="callout callout-warn">
          <div className="callout-title">No API key is set</div>
          Put one in <code>.env</code> as <code>ANTHROPIC_API_KEY</code> and restart <code>zwans serve</code>, or try the
          demo below, which needs none.
        </div>
      )}

      <form className="panel glass home-start" onSubmit={start}>
        <h1>What should Zwans work on?</h1>
        <textarea
          className="textarea home-task"
          placeholder="Describe the task. Zwans reads the code, makes the change, and runs the checks."
          aria-label="Task"
          value={task}
          rows={3}
          onChange={(e) => setTask(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && workspace.trim()) void start(e);
          }}
        />
        <div className="row">
          <div className="folder-field">
            <FolderOpen size={15} aria-hidden="true" />
            <input
              className="mono"
              placeholder="/path/to/project"
              aria-label="Folder to work in"
              value={workspace}
              onChange={(e) => setWorkspace(e.target.value)}
              list="recent-folders"
              required
            />
            {canPick && (
              <button
                type="button"
                className="button button-quiet"
                onClick={async () => {
                  const folder = await window.zwansDesktop?.pickFolder();
                  if (folder) setWorkspace(folder);
                }}
              >
                Choose…
              </button>
            )}
          </div>
          <div className="segmented" role="radiogroup" aria-label="Permission mode">
            {MODES.map((m) => (
              <button
                key={m.id}
                type="button"
                role="radio"
                aria-checked={mode === m.id}
                aria-current={mode === m.id ? "page" : undefined}
                title={m.about}
                onClick={() => setMode(m.id)}
              >
                {m.label}
              </button>
            ))}
          </div>
          <button className="button button-primary" disabled={busy !== null || !workspace.trim()}>
            {busy === "start" ? "Starting…" : "Start"}
          </button>
        </div>
        <p className="muted small">{MODES.find((m) => m.id === mode)?.about}. ⌘↵ starts.</p>
        <datalist id="recent-folders">
          {folders.map(([path]) => (
            <option key={path} value={path} />
          ))}
        </datalist>
      </form>
      {problem && <div className="notice notice-bad">{problem}</div>}

      <div className="home-grid">
        <section className="panel glass">
          <h2 style={{ marginTop: 0 }}>Demo, no key needed</h2>
          <p className="muted">
            A scripted model drives the real harness: the tools run in a copy of a small project, you approve the edits,
            and the under-the-hood panel fills in as it goes. It compacts on the second task so you can see one.
          </p>
          <button className="demo-option" onClick={() => void startDemo()} disabled={busy !== null}>
            <Play size={16} aria-hidden="true" />
            <span style={{ flex: 1 }}>
              <span className="demo-title">{busy === "demo" ? "Starting…" : "Fix a failing test"}</span>
              <span className="muted small">{demo?.prompts[0] ?? "calc: one test fails on purpose"}</span>
            </span>
            <span className="pill pill-quiet">scripted model</span>
          </button>
          {failed && failedRun && (
            <Link
              className="demo-option"
              href={`/evals/transcript/?run=${encodeURIComponent(failedRun.name)}&file=${encodeURIComponent(failed.transcript)}`}
            >
              <ScrollText size={16} aria-hidden="true" />
              <span style={{ flex: 1 }}>
                <span className="demo-title">
                  {failed.task}, attempt {failed.repeat}
                </span>
                <span className="muted small">A failed attempt from {failedRun.name}</span>
              </span>
              <span className="pill pill-quiet">real eval transcript</span>
            </Link>
          )}
        </section>

        <section className="panel glass">
          <h2 style={{ marginTop: 0 }}>Recent folders</h2>
          {folders.length === 0 && <p className="muted">None yet.</p>}
          {folders.map(([path, when]) => (
            <button key={path} className="folder-row" onClick={() => setWorkspace(path)} title="Use this folder">
              <span className="mono">{path.replace(/^\/Users\/[^/]+/, "~")}</span>
              <span className="muted small">{when.replace("T", " ").slice(0, 10)}</span>
            </button>
          ))}
        </section>
      </div>
    </main>
  );
}
