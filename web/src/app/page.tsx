"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { TokenMissing, useApi, useHasToken } from "@/components/useApi";
import { api, type Mode, type SessionList, type SessionStatus } from "@/lib/api";

export default function SessionsPage() {
  const hasToken = useHasToken();
  const router = useRouter();
  const { data, error } = useApi<SessionList>(hasToken ? "/api/sessions" : null);
  const [workspace, setWorkspace] = useState("");
  const [mode, setMode] = useState<Mode>("ask");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const go = (id: string) => router.push(`/session/?id=${encodeURIComponent(id)}`);

  const start = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      const status = await api<SessionStatus>("/api/sessions", {
        method: "POST",
        body: JSON.stringify({ workspace, mode }),
      });
      go(status.id);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  const reopen = async (id: string) => {
    setProblem(null);
    try {
      await api<SessionStatus>(`/api/sessions/${encodeURIComponent(id)}/open`, { method: "POST" });
      go(id);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
    }
  };

  if (hasToken === false) {
    return (
      <main className="page">
        <h1>Sessions</h1>
        <TokenMissing />
      </main>
    );
  }

  return (
    <main className="page">
      <h1>Sessions</h1>
      <p className="muted">Start a session in a folder, or pick up a saved one.</p>

      <form className="row" onSubmit={start} style={{ marginTop: 16 }}>
        <input
          className="input mono"
          style={{ flex: 1, minWidth: 280 }}
          placeholder="/path/to/project"
          aria-label="Workspace folder"
          value={workspace}
          onChange={(e) => setWorkspace(e.target.value)}
          required
        />
        <select className="select" aria-label="Permission mode" value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
          <option value="ask">ask before changes</option>
          <option value="auto">auto: edits and local commands run</option>
          <option value="read-only">read-only</option>
        </select>
        <button className="button button-primary" disabled={busy || !workspace.trim()}>
          {busy ? "Starting…" : "New session"}
        </button>
      </form>
      {(problem || error) && <div className="notice notice-bad">{problem ?? error}</div>}

      <h2>Open now</h2>
      {data && data.live.length === 0 && <p className="muted">None.</p>}
      {data && data.live.length > 0 && (
        <table className="table">
          <tbody>
            {data.live.map((s) => (
              <tr key={s.id}>
                <td>
                  <Link href={`/session/?id=${encodeURIComponent(s.id)}`}>{s.title || "(no prompt yet)"}</Link>
                  <div className="muted mono">{s.workspace}</div>
                </td>
                <td>{s.running ? "running" : s.waiting_for.length ? "waiting for you" : "idle"}</td>
                <td className="num">${s.dollars.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <h2>Saved</h2>
      {data && data.saved.length === 0 && <p className="muted">No saved sessions yet.</p>}
      {data && data.saved.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Session</th>
              <th>Updated</th>
              <th className="num">Turns</th>
              <th className="num">Cost</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {data.saved.map((s) => (
              <tr key={s.id}>
                <td>
                  {s.title || <span className="muted">(no prompt)</span>}
                  <div className="muted mono">
                    {s.id} · {s.workspace}
                  </div>
                </td>
                <td>{s.updated_at.replace("T", " ").slice(0, 16)}</td>
                <td className="num">{s.turns}</td>
                <td className="num">${s.dollars.toFixed(4)}</td>
                <td>
                  <button className="button" onClick={() => reopen(s.id)}>
                    {s.live ? "Open" : "Resume"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
