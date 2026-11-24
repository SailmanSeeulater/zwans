import { describe, expect, it } from "vitest";
import { followAfterScroll, PIN_AT, UNPIN_AT } from "./scrolling";

describe("followAfterScroll", () => {
  it("follows again only back at the very end", () => {
    expect(followAfterScroll(false, 0)).toBe(true);
    expect(followAfterScroll(false, PIN_AT)).toBe(true);
    expect(followAfterScroll(false, PIN_AT + 1)).toBe(false);
  });

  it("keeps what it was a little way up, so a small scroll up isn't undone", () => {
    expect(followAfterScroll(false, 30)).toBe(false);
    expect(followAfterScroll(true, 30)).toBe(true);
  });

  it("stops following well away from the end", () => {
    expect(followAfterScroll(true, UNPIN_AT)).toBe(false);
    expect(followAfterScroll(true, 2000)).toBe(false);
  });
});
