/**
 * Plan mode: the model looks and proposes, and nothing changes until the plan is approved.
 * The server says whether it's on in the status; the events say whether a plan has been
 * written since it went on, which is when there's something to approve.
 */
import type { RawEvent } from "./events";

/** Whether a turn has run since plan mode last went on: a plan to carry out. */
export function hasPlan(events: RawEvent[], planning: boolean): boolean {
  if (!planning) return false;
  let on = -1;
  let turn = -1;
  events.forEach((event, index) => {
    if (event.type === "plan_mode" && event.on === true) on = index;
    else if (event.type === "turn_ended") turn = index;
  });
  return on >= 0 && turn > on;
}
