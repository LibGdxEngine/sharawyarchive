"use client";

import { useCallback, useSyncExternalStore } from "react";
import {
  readStoredMode,
  storeMode,
  type SearchMode,
} from "@/lib/search-mode";

const CHANGE_EVENT = "search-mode-change";

function subscribe(onStoreChange: () => void): () => void {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(CHANGE_EVENT, onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(CHANGE_EVENT, onStoreChange);
  };
}

/**
 * The reader's remembered search mode, shared by every toggle on the page.
 * The server snapshot is always `exact`, so prerendered markup matches and the
 * remembered mode appears on hydration — the same recipe as
 * `usePrefersReducedMotion`.
 */
export function useSearchMode(): [SearchMode, (mode: SearchMode) => void] {
  const mode = useSyncExternalStore(subscribe, readStoredMode, () => "exact" as const);
  const setMode = useCallback((next: SearchMode) => {
    storeMode(next);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);
  return [mode, setMode];
}
