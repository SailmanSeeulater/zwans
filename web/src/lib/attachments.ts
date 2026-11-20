/**
 * Images attached to a prompt, and what undoing turns would put back. Kept apart from the
 * components so the rules can be tested.
 */

import type { FileChange, UndoableTurn } from "./api";

/** The types the API takes. The server checks the bytes again, whatever the name says. */
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
/** The API's limit is 5 MB once base64-encoded. */
export const MAX_IMAGE_BYTES = 3_750_000;
export const MAX_IMAGES = 5;

export interface Attachment {
  name: string;
  /** base64, without the data: prefix */
  data: string;
  /** a data: URL, for the thumbnail */
  url: string;
}

/** Why a file can't be attached, or null when it can. */
export function attachProblem(file: { name: string; type: string; size: number }, attached: number): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return `${file.name} isn't a PNG, JPEG, GIF or WebP image.`;
  if (file.size > MAX_IMAGE_BYTES) {
    const mb = (file.size / 1_000_000).toFixed(1);
    return `${file.name} is ${mb} MB; images can be at most ${MAX_IMAGE_BYTES / 1_000_000} MB.`;
  }
  if (attached >= MAX_IMAGES) return `A message can carry at most ${MAX_IMAGES} images.`;
  return null;
}

export function readAttachment(file: File): Promise<Attachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result);
      resolve({ name: file.name || "pasted image", data: url.slice(url.indexOf(",") + 1), url });
    };
    reader.onerror = () => reject(new Error(`Couldn't read ${file.name}.`));
    reader.readAsDataURL(file);
  });
}

/** The files undoing `turn` and every later turn would change, each once, with what it
 * changed in the first of those turns that touched it. */
export function changesFrom(turns: UndoableTurn[], turn: number): FileChange[] {
  const seen = new Map<string, FileChange>();
  for (const t of [...turns].sort((a, b) => a.turn - b.turn)) {
    if (t.turn < turn) continue;
    for (const change of t.changes) if (!seen.has(change.path)) seen.set(change.path, change);
  }
  return [...seen.values()];
}

/** "Removed notes.md, which was new; restored calc.py.", from what undoing changed. */
export function describeUndo(undone: FileChange[]): string {
  if (undone.length === 0) return "No files had changed since then.";
  const removed = undone.filter((c) => c.status === "deleted").map((c) => c.path);
  const restored = undone.filter((c) => c.status !== "deleted").map((c) => c.path);
  const parts: string[] = [];
  if (removed.length) parts.push(`removed ${names(removed)}, which ${removed.length === 1 ? "was" : "were"} new`);
  if (restored.length) parts.push(`restored ${names(restored)}`);
  const text = parts.join("; ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}

function names(paths: string[], shown = 4): string {
  const parts = paths.slice(0, shown);
  if (paths.length > shown) parts.push(`${paths.length - shown} more`);
  return parts.join(", ");
}
