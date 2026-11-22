"use client";

import { Bell, BellOff, Check, Monitor, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { ACCENTS, DEFAULT_PREFS, savePrefs, type Prefs } from "@/lib/prefs";
import { usePrefs } from "@/lib/usePrefs";
import { chooseTheme, readChoice, THEMES, type ThemeChoice } from "@/lib/theme";
import { DiffCount } from "./Glance";
import { Spark } from "./Working";

type Option<T extends string> = { id: T; label: string };

/** A row of buttons, one of them chosen. */
function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: Option<T>[]; onChange: (next: T) => void }) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map((option) => (
        <button key={option.id} role="radio" aria-checked={value === option.id} onClick={() => onChange(option.id)}>
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (next: boolean) => void }) {
  return (
    <button className="toggle" role="switch" aria-checked={checked} aria-label={label} onClick={() => onChange(!checked)}>
      <span className="toggle-knob" />
    </button>
  );
}

function Row({ title, about, stack = false, children }: { title: string; about?: string; stack?: boolean; children: React.ReactNode }) {
  return (
    <div className="settings-row" data-stack={stack || undefined}>
      <div className="settings-row-text">
        <div className="settings-row-title">{title}</div>
        {about && <div className="settings-row-about">{about}</div>}
      </div>
      <div className="settings-row-control">{children}</div>
    </div>
  );
}

/** A few lines of a session, drawn with the real styles, so every choice shows at once. */
function Preview() {
  return (
    <div className="settings-preview" aria-hidden="true">
      <div className="prompt">Fix the failing test in calc.py</div>
      <div className="tool settings-preview-tool">
        <div className="settings-preview-summary">
          <span className="tool-mark tone-ok">✓</span>
          <span className="tool-name">Edit</span>
          <span className="tool-arg">calc.py</span>
          <DiffCount diff={"+    return a + b\n-    return a - b\n+\n"} />
          <span className="tool-state">0.02 s</span>
        </div>
      </div>
      <div className="working" style={{ animation: "none" }}>
        <Spark />
        <span className="working-verb shimmer">Running the tests</span>
        <span className="working-meta">
          <span>12s</span>
          <span>↓ 1.4k</span>
        </span>
      </div>
    </div>
  );
}

export function SettingsView() {
  const prefs = usePrefs();
  const set = (change: Partial<Prefs>) => savePrefs(change);
  const [theme, setTheme] = useState<ThemeChoice>("system");
  const [permission, setPermission] = useState<NotificationPermission | "unsupported">("default");

  useEffect(() => {
    // localStorage and Notification only exist in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTheme(readChoice());
    setPermission(typeof Notification === "undefined" ? "unsupported" : Notification.permission);
  }, []);

  const pickTheme = (next: ThemeChoice) => {
    chooseTheme(next);
    setTheme(next);
  };

  const askToNotify = async () => {
    if (typeof Notification === "undefined") return;
    setPermission(await Notification.requestPermission());
  };

  return (
    <main className="page settings">
      <h1>Settings</h1>
      <p className="muted">These are kept in this browser, and every change shows straight away.</p>

      <Preview />

      <section className="settings-section">
        <h2>Appearance</h2>
        <Row title="Theme" about="Light or dark, each with its own page colour and accent." stack>
          <div className="theme-grid" role="radiogroup" aria-label="Theme">
            <button role="radio" aria-checked={theme === "system"} className="theme-tile" onClick={() => pickTheme("system")} title="Paper by day, Graphite by night">
              <Monitor size={16} aria-hidden="true" />
              <span>Match system</span>
            </button>
            {THEMES.map((t) => (
              <button key={t.id} role="radio" aria-checked={theme === t.id} className="theme-tile" onClick={() => pickTheme(t.id)} title={t.about}>
                <span className="theme-swatch" data-theme={t.id} aria-hidden="true" />
                <span>{t.name}</span>
                {theme === t.id && <Check size={13} aria-hidden="true" />}
              </button>
            ))}
          </div>
        </Row>
        <Row title="Accent" about="Buttons, your messages, edits and the working spark. Each has a lighter shade for the dark themes.">
          <div className="accent-row" role="radiogroup" aria-label="Accent">
            {ACCENTS.map((a) => (
              <button
                key={a.id}
                role="radio"
                aria-checked={prefs.accent === a.id}
                aria-label={a.name}
                title={a.name}
                className="accent-swatch"
                data-swatch={a.id}
                onClick={() => set({ accent: a.id })}
              >
                {prefs.accent === a.id && <Check size={13} aria-hidden="true" />}
              </button>
            ))}
          </div>
        </Row>
        <Row title="Text size">
          <Segmented
            label="Text size"
            value={prefs.text}
            options={[
              { id: "small", label: "Small" },
              { id: "medium", label: "Medium" },
              { id: "large", label: "Large" },
            ]}
            onChange={(text) => set({ text })}
          />
        </Row>
        <Row title="Density" about="Compact fits more of a long session on screen.">
          <Segmented
            label="Density"
            value={prefs.density}
            options={[
              { id: "comfortable", label: "Comfortable" },
              { id: "compact", label: "Compact" },
            ]}
            onChange={(density) => set({ density })}
          />
        </Row>
        <Row title="Conversation width">
          <Segmented
            label="Conversation width"
            value={prefs.width}
            options={[
              { id: "normal", label: "Normal" },
              { id: "wide", label: "Wide" },
            ]}
            onChange={(width) => set({ width })}
          />
        </Row>
        <Row title="Motion" about="Animations while it works. System follows your computer's reduce motion setting.">
          <Segmented
            label="Motion"
            value={prefs.motion}
            options={[
              { id: "system", label: "System" },
              { id: "full", label: "On" },
              { id: "reduced", label: "Off" },
            ]}
            onChange={(motion) => set({ motion })}
          />
        </Row>
      </section>

      <section className="settings-section">
        <h2>Conversation</h2>
        <Row title="Thinking" about="The model's thinking, folded to its latest line or shown in full.">
          <Segmented
            label="Thinking"
            value={prefs.thinking}
            options={[
              { id: "folded", label: "Folded" },
              { id: "open", label: "Open" },
            ]}
            onChange={(thinking) => set({ thinking })}
          />
        </Row>
      </section>

      <section className="settings-section">
        <h2>Notifications</h2>
        <Row
          title="Desktop notifications"
          about={
            permission === "granted"
              ? "Allowed. They only show while Zwans's window isn't the one you're looking at."
              : permission === "denied"
                ? "Blocked in this browser's site settings."
                : permission === "unsupported"
                  ? "This browser can't show them."
                  : "Zwans needs your permission first."
          }
        >
          {permission === "granted" ? (
            <span className="pill pill-quiet">
              <Bell size={12} aria-hidden="true" /> On
            </span>
          ) : permission === "default" ? (
            <button className="button" onClick={() => void askToNotify()}>
              <Bell size={14} aria-hidden="true" /> Allow
            </button>
          ) : (
            <span className="pill pill-quiet">
              <BellOff size={12} aria-hidden="true" /> Off
            </span>
          )}
        </Row>
        <Row title="When a turn finishes">
          <Toggle label="Notify when a turn finishes" checked={prefs.notifyDone} onChange={(notifyDone) => set({ notifyDone })} />
        </Row>
        <Row title="When it needs your answer" about="A permission question, or a question from the model.">
          <Toggle label="Notify when it needs your answer" checked={prefs.notifyWaiting} onChange={(notifyWaiting) => set({ notifyWaiting })} />
        </Row>
        <Row title="Sound" about="A soft chime with each notification.">
          <Toggle label="Play a sound" checked={prefs.sound} onChange={(sound) => set({ sound })} />
        </Row>
      </section>

      <section className="settings-section">
        <h2>New sessions</h2>
        <Row title="Start in" about="The permission mode the home screen picks for a new session.">
          <Segmented
            label="Start in"
            value={prefs.newMode}
            options={[
              { id: "read-only", label: "Read-only" },
              { id: "ask", label: "Ask" },
              { id: "auto", label: "Auto" },
            ]}
            onChange={(newMode) => set({ newMode })}
          />
        </Row>
        <Row title="Model" about="Picking a model on the home screen remembers it here. Empty uses your config's.">
          <div className="row" style={{ gap: 6 }}>
            <span className="pill pill-quiet mono">{prefs.newModel || "from the config"}</span>
            {prefs.newModel && (
              <button className="msg-action" onClick={() => set({ newModel: "" })} aria-label="Use the config's model" title="Use the config's model">
                <RotateCcw size={13} aria-hidden="true" />
              </button>
            )}
          </div>
        </Row>
      </section>

      <div className="settings-foot">
        <button className="button button-quiet" onClick={() => set(DEFAULT_PREFS)}>
          <RotateCcw size={14} aria-hidden="true" /> Reset to defaults
        </button>
      </div>
    </main>
  );
}
