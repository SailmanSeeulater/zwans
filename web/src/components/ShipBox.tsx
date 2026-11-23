"use client";

import { Check, ExternalLink, GitBranch, GitPullRequest, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, type GitInfo, type Shipped } from "@/lib/api";

interface Props {
  sessionId: string;
  /** False while a turn runs: its work isn't finished. */
  ready: boolean;
  onClose: () => void;
}

/**
 * Shipping a session's work: a branch, a commit of the files it changed (and only those),
 * a push, and a pull request through GitHub's gh. The branch, title and body start from the
 * session and are edited here; nothing happens until the button is pressed.
 */
export function ShipBox({ sessionId, ready, onClose }: Props) {
  const [info, setInfo] = useState<GitInfo | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [branch, setBranch] = useState("");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [push, setPush] = useState(true);
  const [pr, setPr] = useState(true);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Shipped | null>(null);

  useEffect(() => {
    let current = true;
    api<GitInfo>(`/api/sessions/${encodeURIComponent(sessionId)}/git`)
      .then((found) => {
        if (!current) return;
        setInfo(found);
        if (found.draft) {
          setBranch(found.draft.branch);
          setTitle(found.draft.title);
          setBody(found.draft.body);
        }
        const state = found.state;
        setPush(Boolean(state.remote));
        setPr(Boolean(state.remote && state.github && state.gh));
      })
      .catch((error: unknown) => current && setProblem(error instanceof Error ? error.message : String(error)));
    return () => {
      current = false;
    };
  }, [sessionId]);

  const ship = async () => {
    setBusy(true);
    setProblem(null);
    try {
      setDone(
        await api<Shipped>(`/api/sessions/${encodeURIComponent(sessionId)}/ship`, {
          method: "POST",
          body: JSON.stringify({ branch, title, body, push, pull_request: push && pr }),
        }),
      );
    } catch (error) {
      setProblem(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  const state = info?.state;
  const files = info?.files ?? [];
  const canPr = Boolean(state?.remote && state.github && state.gh);
  const label = !push ? "Commit" : pr && canPr ? "Commit, push and open PR" : "Commit and push";

  return (
    <section className="ship" aria-label="Ship these changes">
      <header className="ship-head">
        <GitPullRequest size={15} aria-hidden="true" />
        <strong>Ship these changes</strong>
        <button className="button button-quiet icon-button" onClick={onClose} aria-label="Close">
          <X size={14} aria-hidden="true" />
        </button>
      </header>
      {!info && !problem && (
        <p className="muted small">
          <Loader2 size={12} className="spin" aria-hidden="true" /> Looking at the repository…
        </p>
      )}
      {state && !state.repo && <p className="muted small">{state.problem}</p>}
      {done ? (
        <div className="ship-done">
          <ul className="ship-steps">
            {done.steps.map((step) => (
              <li key={step.name} data-ok={step.ok || undefined}>
                {step.ok ? <Check size={13} aria-hidden="true" /> : <X size={13} aria-hidden="true" />}
                <span>{step.detail}</span>
              </li>
            ))}
          </ul>
          {done.url && (
            <a className="button button-primary" href={done.url} target="_blank" rel="noreferrer">
              <ExternalLink size={13} aria-hidden="true" /> Open the pull request
            </a>
          )}
        </div>
      ) : (
        state?.repo && (
          <form
            className="ship-form"
            onSubmit={(event) => {
              event.preventDefault();
              void ship();
            }}
          >
            <p className="muted small">
              {files.length} file{files.length === 1 ? "" : "s"} from this session go in the commit; anything else
              changed in the folder stays out.
              {state.on_base && ` You're on ${state.base}, so this makes a new branch.`}
            </p>
            <label className="ship-field">
              <span>
                <GitBranch size={12} aria-hidden="true" /> Branch
              </span>
              <input className="mono" value={branch} onChange={(e) => setBranch(e.target.value)} required />
            </label>
            <label className="ship-field">
              <span>Title</span>
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />
            </label>
            <label className="ship-field">
              <span>Description</span>
              <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={6} />
            </label>
            <label className="ship-check">
              <input type="checkbox" checked={push} disabled={!state.remote} onChange={(e) => setPush(e.target.checked)} />
              <span>
                Push to origin
                {!state.remote && <span className="muted small"> · there&apos;s no remote called origin</span>}
              </span>
            </label>
            <label className="ship-check">
              <input
                type="checkbox"
                checked={push && pr}
                disabled={!push || !canPr}
                onChange={(e) => setPr(e.target.checked)}
              />
              <span>
                Open a pull request into <span className="mono">{state.base || "the base branch"}</span>
                {!state.github && state.remote && <span className="muted small"> · origin isn&apos;t on GitHub</span>}
                {state.github && !state.gh && (
                  <span className="muted small"> · install gh and run gh auth login</span>
                )}
              </span>
            </label>
            <button className="button button-primary" disabled={busy || !ready || files.length === 0}>
              {busy ? "Working…" : label}
            </button>
            {!ready && <p className="muted small">Wait for the turn to finish first.</p>}
          </form>
        )
      )}
      {problem && <p className="ship-problem small">{problem}</p>}
    </section>
  );
}
