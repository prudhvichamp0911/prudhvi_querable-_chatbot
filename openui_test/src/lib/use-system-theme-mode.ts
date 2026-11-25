"use client";

import { useSyncExternalStore } from "react";

/**
 * Same behaviour as useSystemThemeMode from @openuidev/react-ui. Kept local so
 * the login/signup pages don't pull the whole OpenUI library into their
 * server bundle (that duplicate pushed the Cloudflare Worker over its size cap).
 */
const QUERY = "(prefers-color-scheme: dark)";
const getSnapshot = () => (window.matchMedia(QUERY).matches ? "dark" : "light");
const getServerSnapshot = () => "light" as const;
const subscribe = (onStoreChange: () => void) => {
  const query = window.matchMedia(QUERY);
  query.addEventListener("change", onStoreChange);
  return () => query.removeEventListener("change", onStoreChange);
};

export function useSystemThemeMode(): "dark" | "light" {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
