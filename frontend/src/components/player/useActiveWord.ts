"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import { useAudioStore } from "@/lib/audio-store";
import { findActiveWordIndex } from "@/lib/transcript";
import type { TranscriptWord } from "@/types/models";

/**
 * Index of the word currently being spoken, or -1.
 *
 * Driven by requestAnimationFrame rather than the `timeupdate` event: the
 * media element only fires `timeupdate` ~4×/second, which is visibly late for
 * word-level highlighting. Each frame does one binary search (~13 comparisons
 * on a 6000-word transcript) and bails out without touching React state when
 * the index has not moved — so a React render happens only at word boundaries,
 * a few times per second, not 60×.
 */
export function useActiveWordIndex(
  segmentId: number,
  words: TranscriptWord[]
): number {
  const [activeIndex, setActiveIndex] = useState(-1);

  useEffect(() => {
    let frame = 0;
    let lastIndex = -2; // sentinel: never equals a real result on frame 1

    const tick = (): void => {
      frame = requestAnimationFrame(tick);

      // Read the element straight from the store rather than subscribing:
      // this loop must not cause renders of its own.
      const { current, _el } = useAudioStore.getState();
      if (!_el || current === null || current.segmentId !== segmentId) return;

      const next = findActiveWordIndex(words, _el.currentTime * 1000);
      if (next === lastIndex) return; // early bail — the common case
      lastIndex = next;
      setActiveIndex(next);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [segmentId, words]);

  return activeIndex;
}

// ---------------------------------------------------------------------------
// Reduced motion
// ---------------------------------------------------------------------------

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

function subscribeReducedMotion(onStoreChange: () => void): () => void {
  const query = window.matchMedia(REDUCED_MOTION_QUERY);
  query.addEventListener("change", onStoreChange);
  return () => query.removeEventListener("change", onStoreChange);
}

function getReducedMotion(): boolean {
  return window.matchMedia(REDUCED_MOTION_QUERY).matches;
}

/**
 * `true` while the viewer has asked the OS to minimise motion. Callers use it
 * to swap smooth auto-scroll for instant jumps; the highlight transition is
 * zeroed by the global media query in globals.css.
 */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotion,
    () => false // server render: assume motion is allowed
  );
}
