"use client";

import { ExternalLink, Globe, PanelRightClose, Plus, RotateCw, X } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import {
  clampWidth,
  DEFAULT_WIDTH,
  HOOD,
  MAX_PAGES,
  tabLabel,
  toUrl,
  withNewPage,
  withoutPage,
  type PageTab,
  type PaneState,
} from "@/lib/pane";

interface Props {
  state: PaneState;
  onChange: (next: PaneState) => void;
  hood: ReactNode;
  /** Called in each frame of a drag, after the width is written, to keep the conversation's place. */
  onResizeFrame?: () => void;
}

const KEY_STEP = 24; // pixels an arrow key moves the edge

/**
 * The pane beside the conversation, and the edge that resizes it. Its tabs are "Under the
 * hood" and any pages opened beside the conversation. Both elements are children of the
 * session's row, which holds the width as --pane-width.
 */
export function SidePane({ state, onChange, hood, onResizeFrame }: Props) {
  const handle = useRef<HTMLDivElement>(null);
  const drag = useRef<{ startX: number; from: number; next: number; frame: number } | null>(null);
  const tabs = useRef<HTMLDivElement>(null);

  // A drag writes the width straight to the row's style, once a frame, and React hears of
  // it only when the drag ends: re-rendering the conversation on every pointer event is
  // what makes a resize stutter.
  const row = () => handle.current?.parentElement ?? null;
  const paint = (width: number) => {
    row()?.style.setProperty("--pane-width", `${width}px`);
    onResizeFrame?.();
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    const session = row();
    if (event.button !== 0 || !session) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    const pane = session.querySelector<HTMLElement>(".pane");
    const from = pane?.getBoundingClientRect().width ?? state.width;
    drag.current = { startX: event.clientX, from, next: from, frame: 0 };
    session.dataset.resizing = "";
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const session = row();
    const current = drag.current;
    if (!current || !session) return;
    current.next = clampWidth(current.from + current.startX - event.clientX, session.clientWidth);
    if (current.frame) return;
    current.frame = requestAnimationFrame(() => {
      current.frame = 0;
      if (drag.current === current) paint(current.next);
    });
  };

  const endDrag = () => {
    const current = drag.current;
    if (!current) return;
    drag.current = null;
    cancelAnimationFrame(current.frame);
    delete row()?.dataset.resizing;
    paint(current.next);
    if (current.next !== state.width) onChange({ ...state, width: current.next });
  };

  useEffect(
    () => () => {
      if (drag.current) cancelAnimationFrame(drag.current.frame);
    },
    [],
  );

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const session = row();
    const step = { ArrowLeft: KEY_STEP, ArrowRight: -KEY_STEP }[event.key];
    if (!session || (step === undefined && event.key !== "Home")) return;
    event.preventDefault();
    const wanted = step === undefined ? DEFAULT_WIDTH : state.width + step;
    onChange({ ...state, width: clampWidth(wanted, session.clientWidth) });
  };

  const show = (active: string) => onChange({ ...state, active });
  const open = () => onChange(withNewPage(state, `p${Date.now().toString(36)}`));
  const setUrl = (id: string, url: string) =>
    onChange({ ...state, pages: state.pages.map((p) => (p.id === id ? { ...p, url } : p)) });

  // Arrow keys move between tabs, as in any tab list.
  const onTabKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const ids = [HOOD, ...state.pages.map((p) => p.id)];
    const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (move === undefined) return;
    event.preventDefault();
    const next = ids[(ids.indexOf(state.active) + move + ids.length) % ids.length] ?? HOOD;
    show(next);
    tabs.current?.querySelector<HTMLElement>(`[data-tab="${next}"]`)?.focus();
  };

  return (
    <>
      <div
        ref={handle}
        className="pane-resizer"
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize the side pane"
        aria-valuenow={state.width}
        tabIndex={0}
        title="Drag to resize. Double-click to reset."
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onLostPointerCapture={endDrag}
        onDoubleClick={() => onChange({ ...state, width: DEFAULT_WIDTH })}
        onKeyDown={onKeyDown}
      />
      <aside className="pane glass" aria-label="Side pane">
        <div className="pane-bar">
          <div className="pane-tabs" role="tablist" aria-label="Side pane tabs" ref={tabs} onKeyDown={onTabKey}>
            <button
              role="tab"
              className="pane-tab"
              data-tab={HOOD}
              aria-selected={state.active === HOOD}
              tabIndex={state.active === HOOD ? 0 : -1}
              onClick={() => show(HOOD)}
            >
              Under the hood
            </button>
            {state.pages.map((page) => (
              <span key={page.id} className="pane-tab-wrap" data-selected={state.active === page.id || undefined}>
                <button
                  role="tab"
                  className="pane-tab"
                  data-tab={page.id}
                  aria-selected={state.active === page.id}
                  tabIndex={state.active === page.id ? 0 : -1}
                  title={page.url || undefined}
                  onClick={() => show(page.id)}
                >
                  <Globe size={12} aria-hidden="true" />
                  <span className="pane-tab-name">{tabLabel(page.url)}</span>
                </button>
                <button
                  className="pane-tab-close"
                  aria-label={`Close ${tabLabel(page.url)}`}
                  onClick={() => onChange(withoutPage(state, page.id))}
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </span>
            ))}
          </div>
          <button
            className="button button-quiet icon-button"
            onClick={open}
            disabled={state.pages.length >= MAX_PAGES}
            aria-label="Open a page in a new tab"
            title={state.pages.length >= MAX_PAGES ? `${MAX_PAGES} tabs is the most` : "Open a page beside the conversation"}
          >
            <Plus size={14} aria-hidden="true" />
          </button>
          <button
            className="button button-quiet icon-button"
            onClick={() => onChange({ ...state, open: false })}
            aria-label="Hide the side pane"
            title="Hide the side pane"
          >
            <PanelRightClose size={14} aria-hidden="true" />
          </button>
        </div>
        <div className="pane-body" role="tabpanel" aria-label="Under the hood" hidden={state.active !== HOOD}>
          {hood}
        </div>
        {/* Every page stays mounted, so switching tabs doesn't reload it. */}
        {state.pages.map((page) => (
          <PageView key={page.id} page={page} hidden={state.active !== page.id} onUrl={(url) => setUrl(page.id, url)} />
        ))}
      </aside>
    </>
  );
}

function PageView({ page, hidden, onUrl }: { page: PageTab; hidden: boolean; onUrl: (url: string) => void }) {
  const [typed, setTyped] = useState(page.url);
  const [refused, setRefused] = useState(false);
  const [loads, setLoads] = useState(0); // a new number loads the page again
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!hidden && !page.url) input.current?.focus();
  }, [hidden, page.url]);

  const go = () => {
    const url = toUrl(typed);
    setRefused(url === null);
    if (url === null) return;
    setTyped(url);
    if (url === page.url) setLoads((n) => n + 1);
    else onUrl(url);
  };

  return (
    <div className="pane-page" role="tabpanel" aria-label={tabLabel(page.url)} hidden={hidden}>
      <form
        className="pane-address"
        onSubmit={(event) => {
          event.preventDefault();
          go();
        }}
      >
        <button
          type="button"
          className="button button-quiet icon-button"
          onClick={() => setLoads((n) => n + 1)}
          disabled={!page.url}
          aria-label="Reload"
          title="Reload"
        >
          <RotateCw size={13} aria-hidden="true" />
        </button>
        <input
          ref={input}
          className="input pane-url"
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
            setRefused(false);
          }}
          placeholder="localhost:3000, or any address"
          aria-label="Address"
          aria-invalid={refused || undefined}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
        />
        {page.url && (
          <a
            className="button button-quiet icon-button"
            href={page.url}
            target="_blank"
            rel="noreferrer"
            aria-label="Open in your browser"
            title="Open in your browser"
          >
            <ExternalLink size={13} aria-hidden="true" />
          </a>
        )}
      </form>
      {refused && (
        <p className="pane-note status-failed" role="alert">
          That isn&apos;t an address. Try something like localhost:3000 or example.com.
        </p>
      )}
      {page.url ? (
        <>
          <iframe
            key={loads}
            className="pane-frame"
            src={page.url}
            title={tabLabel(page.url)}
            sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
            referrerPolicy="no-referrer"
          />
          <p className="pane-note muted">
            Blank? Some sites refuse to show inside another page.{" "}
            <a href={page.url} target="_blank" rel="noreferrer">
              Open it in your browser
            </a>
            .
          </p>
        </>
      ) : (
        <div className="pane-empty muted">
          <Globe size={22} aria-hidden="true" />
          <p>
            Open a page beside the conversation: the project&apos;s dev server, its docs, a design.
          </p>
          <p className="small">Type an address above and press Enter.</p>
        </div>
      )}
    </div>
  );
}
