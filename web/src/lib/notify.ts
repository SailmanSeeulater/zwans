/** When to tell you about a session you're not looking at: a turn that finished, or a
 * question waiting for you. Worked out from one listing of the open sessions to the next. */
import type { SessionStatus } from "./api";

export interface Seen {
  running: boolean;
  waiting: number;
}

export interface Alert {
  id: string;
  kind: "done" | "waiting";
  title: string;
  body: string;
}

export function snapshot(live: SessionStatus[]): Map<string, Seen> {
  return new Map(live.map((s) => [s.id, { running: s.running, waiting: s.waiting_for.length }]));
}

/** What changed since `before` that's worth saying. A session seen for the first time says
 * nothing: it was already like that when the page loaded. */
export function alerts(before: Map<string, Seen>, live: SessionStatus[], wanted: { done: boolean; waiting: boolean }): Alert[] {
  const found: Alert[] = [];
  for (const s of live) {
    const was = before.get(s.id);
    if (!was) continue;
    const title = s.title || (s.chat ? "New chat" : "New session");
    if (wanted.waiting && s.waiting_for.length > was.waiting) {
      const question = s.waiting_for.includes("question");
      found.push({ id: s.id, kind: "waiting", title, body: question ? "Zwans has a question for you." : "Zwans needs your OK to go on." });
    } else if (wanted.done && was.running && !s.running) {
      found.push({ id: s.id, kind: "done", title, body: "Finished." });
    }
  }
  return found;
}

/** A soft two-note chime, made on the spot so there's no sound file to ship. */
export function chime() {
  try {
    const audio = new AudioContext();
    const start = audio.currentTime;
    [659.25, 987.77].forEach((frequency, i) => {
      const tone = audio.createOscillator();
      const gain = audio.createGain();
      tone.type = "sine";
      tone.frequency.value = frequency;
      const at = start + i * 0.12;
      gain.gain.setValueAtTime(0, at);
      gain.gain.linearRampToValueAtTime(0.12, at + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + 0.6);
      tone.connect(gain).connect(audio.destination);
      tone.start(at);
      tone.stop(at + 0.65);
    });
    setTimeout(() => void audio.close(), 1200);
  } catch {
    // No audio here; the notification still shows.
  }
}
