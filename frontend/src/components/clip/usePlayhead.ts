"use client";

import { useAudioStore } from "@/lib/audio-store";

/**
 * Live position of `segmentId` in the global player, or 0 when something else
 * is loaded.
 *
 * The store's `positionMs` updates about four times a second — coarse for
 * word highlighting (that is what useActiveWordIndex's rAF loop is for) but
 * exactly right for a playhead marker on an 84-minute overview strip, and it
 * costs no animation frame of its own.
 */
export function usePlayheadMs(segmentId: number): number {
  return useAudioStore((state) =>
    state.current !== null && state.current.segmentId === segmentId
      ? state.positionMs
      : 0
  );
}

/**
 * The playhead read straight off the media element, for the moment somebody
 * presses "من الموضع".
 *
 * Imperative on purpose: `positionMs` may be up to 250 ms stale, which is a
 * word or two, and capturing the playhead is precisely the operation where
 * that matters.
 */
export function readPlayheadMs(segmentId: number): number {
  const { current, positionMs, _el } = useAudioStore.getState();
  if (current === null || current.segmentId !== segmentId) return 0;
  return _el ? Math.floor(_el.currentTime * 1000) : positionMs;
}
