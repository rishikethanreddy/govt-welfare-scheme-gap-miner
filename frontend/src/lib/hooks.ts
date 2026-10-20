"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { api, getOperatorKey } from "@/lib/api";

export interface ApiState<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/**
 * Fetch `path` (null = skip). Re-fetches when the path changes; optional polling.
 * While a refresh of the same path is in flight the previous data stays visible;
 * data belonging to a different path is never shown.
 */
export function useApi<T = unknown>(path: string | null, opts: { refreshMs?: number } = {}): ApiState<T> {
  const [tick, setTick] = useState(0);
  const [state, setState] = useState<{ path?: string; key?: string; data?: T; error?: Error }>({});
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const key = path ? `${path}#${tick}` : null;

  useEffect(() => {
    if (!path || !key) return;
    const ctl = new AbortController();
    api.get<T>(path, ctl.signal)
      .then((data) => setState({ path, key, data }))
      .catch((error) => {
        if (error.name !== "AbortError") setState((s) => ({ path, key, data: s.path === path ? s.data : undefined, error }));
      });
    return () => ctl.abort();
  }, [path, key]);

  useEffect(() => {
    if (!opts.refreshMs || !path) return;
    const id = setInterval(reload, opts.refreshMs);
    return () => clearInterval(id);
  }, [opts.refreshMs, path, reload]);

  const samePath = !!path && state.path === path;
  return {
    data: samePath ? state.data : undefined,
    error: samePath ? state.error : undefined,
    loading: !!path && state.key !== key,
    reload,
  };
}

function subscribeKey(cb: () => void) {
  window.addEventListener("operator-key-changed", cb);
  window.addEventListener("storage", cb);
  return () => {
    window.removeEventListener("operator-key-changed", cb);
    window.removeEventListener("storage", cb);
  };
}

/** Whether an operator key is present in this browser session (reactive). */
export function useOperatorKeyPresent(): boolean {
  return useSyncExternalStore(subscribeKey, () => !!getOperatorKey(), () => false);
}

const noopSubscribe = () => () => {};

/** True only after hydration (avoids rendering client-only values on the server). */
export function useMounted(): boolean {
  return useSyncExternalStore(noopSubscribe, () => true, () => false);
}
