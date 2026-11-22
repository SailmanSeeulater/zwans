"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";
import type { SessionList } from "@/lib/api";
import { alerts, chime, snapshot, type Seen } from "@/lib/notify";
import { usePrefs } from "@/lib/usePrefs";
import { useApi, useHasToken } from "./useApi";

const REFRESH_MS = 3_000;

/** Desktop notifications for open sessions, while Zwans isn't the window you're looking at.
 * Clicking one brings Zwans forward on that session. Renders nothing. */
export function Notifier() {
  const hasToken = useHasToken();
  const router = useRouter();
  const prefs = usePrefs();
  const { data } = useApi<SessionList>(hasToken ? "/api/sessions" : null, REFRESH_MS);
  const before = useRef<Map<string, Seen> | null>(null);

  useEffect(() => {
    if (!data) return;
    const live = data.live;
    const previous = before.current;
    before.current = snapshot(live);
    if (!previous) return; // the first listing is how things were when the page loaded
    const found = alerts(previous, live, { done: prefs.notifyDone, waiting: prefs.notifyWaiting });
    if (!found.length || (document.visibilityState === "visible" && document.hasFocus())) return;
    if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
    for (const alert of found) {
      const note = new Notification(alert.title, { body: alert.body, tag: `zwans-${alert.id}`, silent: true });
      note.onclick = () => {
        window.focus();
        router.push(`/session/?id=${encodeURIComponent(alert.id)}`);
        note.close();
      };
    }
    if (prefs.sound) chime();
  }, [data, prefs.notifyDone, prefs.notifyWaiting, prefs.sound, router]);

  return null;
}
