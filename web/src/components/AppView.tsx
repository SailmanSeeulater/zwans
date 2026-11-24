"use client";

import { LayoutPanelTop } from "lucide-react";
import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { AppBridge, allowed, themeVariables, viewDocument, type AppView as View, type HostContext } from "@/lib/apps";
import { THEMES } from "@/lib/theme";

/** What a view can reach in a live session: its own server's tools and resources, and the
 * composer. A transcript has none, so a view there shows its result and nothing more. */
export interface AppSession {
  callTool(server: string, name: string, args: Record<string, unknown>): Promise<unknown>;
  readResource(server: string, uri: string): Promise<unknown>;
  /** Put text in the composer for the person to send, or not. */
  draft(text: string): void;
}

export const AppSessionContext = createContext<AppSession | null>(null);

const FIRST_HEIGHT = 160; // px, until the view says how tall it is
const PERMISSION_POLICY: Record<string, string> = { clipboardWrite: "clipboard-write" };

function hostContext(): HostContext {
  const root = document.documentElement;
  const style = getComputedStyle(root);
  const dark = THEMES.find((theme) => theme.id === root.dataset.theme)?.dark ?? false;
  return {
    theme: dark ? "dark" : "light",
    variables: themeVariables((name) => style.getPropertyValue(name)),
    locale: navigator.language,
    timeZone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    platform: "zwansDesktop" in window ? "desktop" : "web",
    hover: matchMedia("(hover: hover)").matches,
    touch: matchMedia("(pointer: coarse)").matches,
  };
}

const notOpen = () => Promise.reject(new Error("This session isn't open, so the view can't reach its server."));

/** An MCP tool's interactive view of its result, under the call (lib/apps.ts). */
export function AppView({ view }: { view: View }) {
  const session = useContext(AppSessionContext);
  const frame = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(FIRST_HEIGHT);
  const document = useMemo(() => viewDocument(view.html, view.csp), [view.html, view.csp]);
  // The session's callbacks change as it re-renders, and the call is parsed again with each
  // event; the bridge reads the latest, and lives as long as the page in the iframe does.
  const latest = useRef(session);
  const call = useRef(view);
  useEffect(() => {
    latest.current = session;
    call.current = view;
  }, [session, view]);

  useEffect(() => {
    const iframe = frame.current;
    if (!iframe) return;
    const view = call.current;
    const bridge = new AppBridge(
      view,
      {
        callTool: (name, args) => latest.current?.callTool(view.server, name, args) ?? notOpen(),
        readResource: (uri) => latest.current?.readResource(view.server, uri) ?? notOpen(),
        openLink: (url) => window.open(url, "_blank", "noopener,noreferrer"),
        message: (text) => {
          if (!latest.current) throw new Error("This session isn't open.");
          latest.current.draft(text);
        },
        resize: setHeight,
      },
      // The sandbox gives the view no origin, so "*" is the only target that reaches it;
      // what it sends back is checked by where it came from instead.
      (message) => iframe.contentWindow?.postMessage(message, "*"),
      hostContext(),
    );
    const onMessage = (event: MessageEvent) => {
      if (event.source === iframe.contentWindow) bridge.receive(event.data);
    };
    window.addEventListener("message", onMessage);
    const themes = new MutationObserver(() => bridge.setContext(hostContext()));
    themes.observe(window.document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      bridge.teardown("The view was closed.");
      themes.disconnect();
      window.removeEventListener("message", onMessage);
    };
  }, [document]);

  const allow = allowed(view.permissions)
    .map((p) => PERMISSION_POLICY[p])
    .filter(Boolean)
    .join("; ");
  return (
    <figure className={`app-view ${view.prefersBorder === false ? "app-view-bare" : ""}`}>
      <figcaption className="app-view-caption">
        <LayoutPanelTop size={12} aria-hidden="true" />
        <span>View from {view.server}</span>
        <span className="app-view-uri" title={view.uri}>
          {view.uri}
        </span>
      </figcaption>
      <iframe
        ref={frame}
        className="app-view-frame"
        title={`${String(view.tool.title ?? view.tool.name ?? "Tool")} view from ${view.server}`}
        // Scripts only: no origin of its own, so no cookies, storage or Zwans's API, and no
        // forms, popups or navigating this page.
        sandbox="allow-scripts"
        srcDoc={document}
        allow={allow || undefined}
        referrerPolicy="no-referrer"
        style={{ height }}
      />
    </figure>
  );
}
