"use client";

import { useMemo, useState } from "react";
import { contextTotal, counted } from "@/lib/calls";
import { piecesAt, tilesFor } from "@/lib/context";
import { pct, tokens } from "@/lib/format";
import { squarify } from "@/lib/treemap";
import { PARTS } from "../UnderTheHood";
import { Empty, type InspectorProps } from "./Inspector";

const W = 1000;
const H = 440;

/** Draft 09: the request of one model call as a map, each tile sized by its tokens. */
export function ContextMap({ events, data, status }: InspectorProps) {
  const main = data.calls.filter((c) => c.purpose === "turn" && !c.subagent);
  const [picked, setPicked] = useState<number | null>(null);
  const index = Math.min(picked ?? main.length - 1, main.length - 1);
  const call = main[index];

  const tiles = useMemo(() => {
    if (!call) return [];
    const all = tilesFor(call.context, piecesAt(events, index));
    // Lay out the four parts first, then each part's pieces inside its own rectangle.
    const parts = squarify(
      PARTS.map((p) => ({ key: p.key, value: call.context[p.key] })),
      { x: 0, y: 0, w: W, h: H },
    );
    return parts.flatMap((part) =>
      squarify(
        all.filter((t) => t.part === part.key),
        part.rect,
      ),
    );
  }, [call, events, index]);

  if (!call) return <Empty>Nothing has been sent to the model yet. The map appears after the first call.</Empty>;

  const total = contextTotal(call.context);
  const compactAt = status?.compact_at ?? 200_000;
  const cachedShare = counted(call) ? call.cacheRead / counted(call) : 0;
  const cheaper = call.prices && call.prices.cache_read ? Math.round(call.prices.input / call.prices.cache_read) : null;

  return (
    <div className="inspect-grid">
      <section className="panel glass">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <div>
            <h1 style={{ margin: 0 }}>{total.toLocaleString()} tokens in context</h1>
            <p className="muted">
              Call {call.n}, turn {call.turn} · {pct(total / compactAt)} of the way to the {tokens(compactAt)} compaction
              point
            </p>
          </div>
          {main.length > 1 && (
            <label className="row small">
              Call
              <input
                type="range"
                min={0}
                max={main.length - 1}
                value={index}
                onChange={(e) => setPicked(Number(e.target.value))}
                aria-label="Which model call to show"
              />
              <span className="mono">
                {index + 1} of {main.length}
              </span>
            </label>
          )}
        </div>
        <div className="treemap" role="img" aria-label={`Context of call ${call.n}`}>
          {tiles.map((t) => {
            const part = PARTS.find((p) => p.key === t.part)!;
            const small = t.rect.w < 90 || t.rect.h < 44;
            return (
              <div
                key={t.id}
                className={`tile ${t.fresh ? "tile-fresh" : ""}`}
                title={`${t.label}: about ${Math.round(t.value).toLocaleString()} tokens${t.fresh ? ", new since the last call" : ""}`}
                style={{
                  left: `${(t.rect.x / W) * 100}%`,
                  top: `${(t.rect.y / H) * 100}%`,
                  width: `${(t.rect.w / W) * 100}%`,
                  height: `${(t.rect.h / H) * 100}%`,
                  background: part.color,
                  color: part.ink,
                }}
              >
                {!small && (
                  <>
                    <span className="tile-label">{t.label}</span>
                    <span className="mono tile-value">{tokens(t.value)}</span>
                  </>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <aside className="panel glass inspect-side">
        <h3>How to read it</h3>
        <ul className="key-list">
          <li>
            <span className="swatch" style={{ background: "var(--s3)" }} />
            Messages between you and the model, by turn
          </li>
          <li>
            <span className="swatch" style={{ background: "var(--s4)" }} />
            What tools sent back: file contents, command output
          </li>
          <li>
            <span className="swatch" style={{ background: "var(--s2)" }} />
            Tool definitions: each tool&apos;s name, description and input schema
          </li>
          <li>
            <span className="swatch" style={{ background: "var(--s1)" }} />
            System prompt: Zwans&apos;s instructions to the model
          </li>
          <li>
            <span className="swatch swatch-fresh" />
            New since the previous call, so not cached yet
          </li>
        </ul>
        <h3>Cached prefix</h3>
        <p>
          <span className="stat-value">{tokens(call.cacheRead)}</span> <span className="muted">· {pct(cachedShare)}</span>
        </p>
        <p className="muted small">
          Everything up to the last cache breakpoint was read from the cache
          {cheaper ? `, at 1/${cheaper} of the input price` : ""}. {tokens(call.cacheWrite)} tokens were written to the
          cache and {tokens(call.input)} were sent at the full price.
        </p>
        <p className="muted small">
          The four parts are the API&apos;s own count, split by size. Within a part, the tiles are estimated from text
          length.
        </p>
      </aside>
    </div>
  );
}
