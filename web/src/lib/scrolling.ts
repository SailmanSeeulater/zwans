/**
 * Whether a conversation keeps following new output to the bottom, after a scroll.
 *
 * Output can arrive many times a second while the model writes, and each arrival scrolls a
 * following conversation to the end. A threshold alone ("within 80px of the end counts as
 * following") turns a small scroll up back into following before the person gets anywhere,
 * so it's two: back at the very end, it follows again; well away from it, it doesn't; in
 * between, it stays as it was. The person's own wheel, touch and keys unpin it at once.
 */
export const PIN_AT = 8; // px from the end that count as being at it
export const UNPIN_AT = 80; // px from the end that count as having left it

export function followAfterScroll(following: boolean, fromEnd: number): boolean {
  if (fromEnd <= PIN_AT) return true;
  if (fromEnd >= UNPIN_AT) return false;
  return following;
}
