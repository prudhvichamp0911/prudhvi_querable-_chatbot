"use client";

import { useCallback, useSyncExternalStore } from "react";

const LOCAL_EVENT = "queryable-local-storage";

// Fallback so toggles still work for the session when storage is blocked.
const memory = new Map<string, string>();

function subscribe(callback: () => void) {
  window.addEventListener("storage", callback);
  window.addEventListener(LOCAL_EVENT, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(LOCAL_EVENT, callback);
  };
}

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key) ?? memory.get(key) ?? null;
  } catch {
    return memory.get(key) ?? null;
  }
}

/** A localStorage value that is SSR-safe (null on the server) and stays in sync across tabs. */
export function useLocalStorage(key: string): [string | null, (value: string) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => read(key),
    () => null,
  );

  const setValue = useCallback(
    (next: string) => {
      memory.set(key, next);
      try {
        window.localStorage.setItem(key, next);
      } catch {
        // Storage unavailable (private mode, blocked site data): keep working without it.
      }
      window.dispatchEvent(new Event(LOCAL_EVENT));
    },
    [key],
  );

  return [value, setValue];
}

const noopSubscribe = () => () => {};

/** Evaluate a browser capability check on the client only (false during SSR). */
export function useBrowserCheck(check: () => boolean): boolean {
  return useSyncExternalStore(noopSubscribe, check, () => false);
}
