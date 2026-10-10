import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

export type AsyncState<T> =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; data: T };

/**
 * Fetch-on-mount with a reload handle. Seven screens had the same fifteen
 * lines of `useCallback` + `useEffect` + three-state union; this is that
 * code, once.
 *
 * The mount pass deliberately does NOT set "loading" first: state already
 * starts there, so setting it again inside the effect is a redundant
 * synchronous render (and the thing `react/set-state-in-effect` is warning
 * about). A user-triggered reload does set it, because there the screen is
 * showing data and needs to say it's fetching.
 *
 * `fetcher` must be stable — pass a module-level function or one wrapped in
 * `useCallback`, or the effect re-runs every render.
 */
export function useAsyncData<T>(
  fetcher: () => Promise<T>,
  fallbackMessage = "Unexpected error loading this screen.",
) {
  const [state, setState] = useState<AsyncState<T>>({ kind: "loading" });

  // No synchronous setState in here: the first statement awaits, so the
  // mount path settles state only once the fetch resolves.
  const fetchInto = useCallback(async () => {
    try {
      setState({ kind: "loaded", data: await fetcher() });
    } catch (err) {
      setState({
        kind: "error",
        message: err instanceof ApiError ? err.message : fallbackMessage,
      });
    }
  }, [fetcher, fallbackMessage]);

  useEffect(() => {
    // fetchInto awaits before it touches state, so nothing here is
    // synchronous. This is the "synchronizing with an external system" case
    // the rule's own guidance carves out: the external system is the HTTP
    // API. The rule can't see past the await, so it is suppressed once,
    // here, rather than in the eight screens that call this hook.
    // eslint-disable-next-line react/set-state-in-effect
    void fetchInto();
  }, [fetchInto]);

  const reload = useCallback(() => {
    setState({ kind: "loading" });
    void fetchInto();
  }, [fetchInto]);

  /** Replace the loaded value in place — for screens that mutate a list. */
  const setData = useCallback((update: (prev: T) => T) => {
    setState((prev) => (prev.kind === "loaded" ? { kind: "loaded", data: update(prev.data) } : prev));
  }, []);

  return { state, reload, setData };
}
