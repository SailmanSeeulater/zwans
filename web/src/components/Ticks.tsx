import { codeSpans } from "@/lib/format";

/** A line the server wrote, with its `backticked` parts shown as code. */
export function Ticks({ text }: { text: string }) {
  return (
    <>
      {codeSpans(text).map((span, i) => (span.code ? <code key={i}>{span.text}</code> : span.text))}
    </>
  );
}
