"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAudioStore } from "@/lib/audio-store";

export interface PlaybackRange {
  startMs: number;
  endMs: number;
}

/**
 * "تشغيل التحديد" — play one span of the loaded segment and pause at its end.
 *
 * The store has no stop-at primitive, and `positionMs` updates only ~4 Hz —
 * too coarse to pause on a word boundary. So while a range is armed, a
 * requestAnimationFrame loop reads the element clock straight off the store
 * (the ClipComposer/useActiveWord precedent) and calls `pause()` at `endMs`.
 *
 * The watcher disarms itself when the listener takes over: a manual pause, a
 * seek outside the range, or a track change all cancel without pausing again.
 */
export function useRangePlayback(segmentId: number): {
  activeRange: PlaybackRange | null;
  playRange(range: PlaybackRange): void;
  stop(): void;
} {
  const [activeRange, setActiveRange] = useState<PlaybackRange | null>(null);
  // The rAF loop must see cancellation immediately, not on the next render.
  const armedRef = useRef<PlaybackRange | null>(null);

  const playRange = (range: PlaybackRange): void => {
    const store = useAudioStore.getState();
    store.seekMs(range.startMs);
    store.play();
    armedRef.current = range;
    setActiveRange(range);
  };

  const stop = useCallback((): void => {
    armedRef.current = null;
    setActiveRange(null);
  }, []);

  useEffect(() => {
    if (activeRange === null) return;

    let frame = 0;
    // The play() above may take a moment to actually start (autoplay policy,
    // buffering); a "manual pause" only counts once playback has been seen.
    let sawPlaying = false;

    const tick = (): void => {
      frame = requestAnimationFrame(tick);
      const armed = armedRef.current;
      if (armed === null) {
        cancelAnimationFrame(frame);
        setActiveRange(null);
        return;
      }

      const { current, isPlaying, _el } = useAudioStore.getState();
      if (!_el || current === null || current.segmentId !== segmentId) {
        stop();
        return;
      }

      const positionMs = _el.currentTime * 1000;
      if (isPlaying) {
        sawPlaying = true;
      } else if (sawPlaying) {
        // The listener paused (or the track ended) — the range is done.
        stop();
        return;
      }

      // A seek that left the range means the listener moved on.
      if (positionMs < armed.startMs - 1_000) {
        stop();
        return;
      }
      if (positionMs >= armed.endMs) {
        useAudioStore.getState().pause();
        stop();
      }
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [activeRange, segmentId, stop]);

  return { activeRange, playRange, stop };
}
