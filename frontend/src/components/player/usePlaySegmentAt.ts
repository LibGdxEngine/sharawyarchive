"use client";

import { useCallback, useRef, useState } from "react";
import { getSegment } from "@/lib/api";
import { useAudioStore } from "@/lib/audio-store";
import type { Segment } from "@/types/models";

/**
 * "Play from here" for anything that knows a segment id and a millisecond —
 * search hits, smart-search citations and passages. Resolves the segment's
 * presigned audio URL on demand (once per segment for the life of the
 * component) and hands it to the global player, so audio starts at the
 * timestamp without leaving the page.
 *
 * `pendingKey`/`failedKey` are whatever key the caller passes, so a list can
 * mark exactly the row that is loading or could not play.
 */
export function usePlaySegmentAt() {
  const load = useAudioStore((s) => s.load);
  const [pendingKey, setPendingKey] = useState<string | number | null>(null);
  const [failedKey, setFailedKey] = useState<string | number | null>(null);
  const segments = useRef(new Map<number, Promise<Segment>>());

  const play = useCallback(
    async (key: string | number, segmentId: number, startMs: number) => {
      setFailedKey(null);
      setPendingKey(key);
      try {
        let pending = segments.current.get(segmentId);
        if (pending === undefined) {
          pending = getSegment(segmentId);
          segments.current.set(segmentId, pending);
        }
        const segment = await pending;
        load(
          {
            segmentId: segment.id,
            title: segment.title,
            audioUrl: segment.audio_url,
            durationMs: segment.duration_ms,
          },
          { startMs, autoplay: true }
        );
      } catch {
        segments.current.delete(segmentId);
        setFailedKey(key);
      } finally {
        setPendingKey(null);
      }
    },
    [load]
  );

  return { play, pendingKey, failedKey };
}
