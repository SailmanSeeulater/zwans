"use client";

import { useCallback, useEffect, useState } from "react";
import { api, readToken } from "@/lib/api";

/** Load one API path, with a way to load it again. `null` waits without loading. */
export function useApi<T>(path: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    if (path === null) return;
    let stale = false;
    api<T>(path)
      .then((result) => {
        if (!stale) {
          setData(result);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!stale) setError(err instanceof Error ? err.message : String(err));
      });
    return () => {
      stale = true;
    };
  }, [path, version]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { data, error, reload };
}

/** Whether this browser has the server's token yet. Unknown (null) until mounted. */
export function useHasToken(): boolean | null {
  const [has, setHas] = useState<boolean | null>(null);
  useEffect(() => {
    // Reads the URL and localStorage, which only exist in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHas(Boolean(readToken()));
    // The link pasted into a tab that's already open changes only the hash.
    const onHash = () => setHas(Boolean(readToken()));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return has;
}

export function TokenMissing() {
  return (
    <div className="notice notice-warn">
      This browser doesn&apos;t have the server&apos;s token yet. Open the link <code>zwans serve</code>{" "}
      printed (the part after <code>#token=</code> is the token).
    </div>
  );
}
