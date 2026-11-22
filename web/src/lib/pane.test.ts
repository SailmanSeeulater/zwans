import { describe, expect, it } from "vitest";
import {
  clampWidth,
  DEFAULT_PANE,
  HOOD,
  MAX_PAGES,
  MIN_MAIN,
  MIN_WIDTH,
  restore,
  tabLabel,
  toUrl,
  withNewPage,
  withoutPage,
} from "./pane";

describe("clampWidth", () => {
  it("keeps the pane between its smallest width and what the conversation can spare", () => {
    expect(clampWidth(500, 1400)).toBe(500);
    expect(clampWidth(100, 1400)).toBe(MIN_WIDTH);
    expect(clampWidth(2000, 1400)).toBe(1400 - MIN_MAIN);
  });

  it("never goes under the smallest width, even in a session too narrow for both", () => {
    expect(clampWidth(500, 600)).toBe(MIN_WIDTH);
  });

  it("gives whole pixels", () => {
    expect(clampWidth(333.6, 1400)).toBe(334);
  });
});

describe("toUrl", () => {
  it("gives a dev server http and anything else https", () => {
    expect(toUrl("localhost:3000")).toBe("http://localhost:3000/");
    expect(toUrl("127.0.0.1:8000/docs")).toBe("http://127.0.0.1:8000/docs");
    expect(toUrl("app.localhost:5173")).toBe("http://app.localhost:5173/");
    expect(toUrl("example.com/a?b=1")).toBe("https://example.com/a?b=1");
  });

  it("keeps a scheme that was typed", () => {
    expect(toUrl("http://example.com")).toBe("http://example.com/");
    expect(toUrl("https://localhost:8443")).toBe("https://localhost:8443/");
  });

  it("refuses what isn't a web page", () => {
    expect(toUrl("")).toBeNull();
    expect(toUrl("how do I center a div")).toBeNull();
    expect(toUrl("javascript://x/%0Aalert(1)")).toBeNull();
    expect(toUrl("file:///etc/passwd")).toBeNull();
    expect(toUrl("notes")).toBeNull();
  });
});

describe("tabLabel", () => {
  it("is the host, with the path when there is one", () => {
    expect(tabLabel("http://localhost:3000/")).toBe("localhost:3000");
    expect(tabLabel("https://example.com/docs/api")).toBe("example.com/docs/api");
    expect(tabLabel("")).toBe("New tab");
  });
});

describe("restore", () => {
  it("falls back to the default for anything that isn't a saved pane", () => {
    expect(restore(null)).toEqual(DEFAULT_PANE);
    expect(restore("wide")).toEqual(DEFAULT_PANE);
  });

  it("drops tabs it can't load and an active tab that's gone", () => {
    const restored = restore({
      open: false,
      width: 512.4,
      pages: [{ id: "a", url: "http://localhost:3000/" }, { id: "b", url: "javascript:alert(1)" }, { id: 3 }],
      active: "b",
    });

    expect(restored).toEqual({
      open: false,
      width: 512,
      pages: [{ id: "a", url: "http://localhost:3000/" }],
      active: HOOD,
    });
  });

  it("doesn't restore a width under the smallest", () => {
    expect(restore({ width: 12 }).width).toBe(MIN_WIDTH);
  });
});

describe("tabs", () => {
  it("opens a new tab and shows it, up to the most allowed", () => {
    let state = { ...DEFAULT_PANE, open: false };
    state = withNewPage(state, "p1");
    expect(state).toMatchObject({ open: true, active: "p1", pages: [{ id: "p1", url: "" }] });

    for (let i = 2; i <= MAX_PAGES + 3; i++) state = withNewPage(state, `p${i}`);
    expect(state.pages).toHaveLength(MAX_PAGES);
    expect(state.active).toBe(`p${MAX_PAGES}`);
  });

  it("shows the neighbour of a closed tab, and Under the hood after the last", () => {
    const pages = ["a", "b", "c"].map((id) => ({ id, url: "" }));
    const state = { ...DEFAULT_PANE, pages, active: "b" };

    expect(withoutPage(state, "b").active).toBe("c");
    expect(withoutPage({ ...state, active: "c" }, "c").active).toBe("b");
    expect(withoutPage(state, "a").active).toBe("b"); // another tab closing leaves the view alone
    expect(withoutPage({ ...state, pages: pages.slice(0, 1), active: "a" }, "a").active).toBe(HOOD);
  });
});
