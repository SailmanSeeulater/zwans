/** A turn's reply as text to copy: what the model wrote, without its thinking or tool calls. */
import type { Turn } from "./events";

export function replyText(turn: Turn): string {
  return turn.items
    .flatMap((item) => (item.kind === "text" ? [item.text.trim()] : []))
    .filter(Boolean)
    .join("\n\n");
}
