"use client";

import { useEffect, useState } from "react";
import { getSegment, getTranscript } from "@/lib/api";
import { getOfflineSegment, getOfflineTranscript } from "@/lib/offline";
import type { Segment, Transcript } from "@/types/models";

export type SegmentData =
  | { status: "loading" }
  | {
      status: "ready";
      segment: Segment;
      /** Null when the segment has not been transcribed yet — the audio
       *  plays, the transcript pane explains itself. */
      transcript: Transcript | null;
      /** Where the data came from — "offline" means the network was gone. */
      source: "network" | "offline";
    }
  | { status: "error" };

/**
 * Segment metadata + transcript for /listen, fetched from the browser.
 *
 * Deliberately not a server fetch. Two things depend on the request being made
 * by the page itself:
 *
 *  1. The service worker only sees requests its clients make. A transcript
 *     fetched on the server never passes through the stale-while-revalidate
 *     route, so it is never in the runtime cache when the network goes away.
 *  2. When the network is already gone, the copies saved by
 *     `saveSegmentOffline` are right here to fall back to.
 *
 * The presigned `audio_url` in a cached segment has long expired; playback of a
 * saved segment goes through `getOfflineAudioUrl` instead.
 */
const LOADING: SegmentData = { status: "loading" };

export function useSegmentData(segmentId: number): SegmentData {
  // The id is kept next to the data so that a change of segment reads as
  // loading during render, rather than through an effect that resets state.
  const [resolved, setResolved] = useState<{ id: number; data: SegmentData }>({
    id: segmentId,
    data: LOADING,
  });

  useEffect(() => {
    let cancelled = false;

    const fromNetwork = async (): Promise<SegmentData> => {
      const segment = await getSegment(segmentId);
      if (segment.transcript_version === null) {
        // Ingested but not yet transcribed: playable, honestly untranscribed.
        return { status: "ready", segment, transcript: null, source: "network" };
      }
      const transcript = await getTranscript(
        segmentId,
        segment.transcript_version
      );
      return { status: "ready", segment, transcript, source: "network" };
    };

    const fromSaved = async (): Promise<SegmentData> => {
      const [segment, transcript] = await Promise.all([
        getOfflineSegment(segmentId),
        getOfflineTranscript(segmentId),
      ]);
      if (segment === null || transcript === null) return { status: "error" };
      return { status: "ready", segment, transcript, source: "offline" };
    };

    void (async () => {
      let next: SegmentData;
      try {
        next = await fromNetwork();
      } catch {
        next = await fromSaved();
      }
      if (!cancelled) setResolved({ id: segmentId, data: next });
    })();

    return () => {
      cancelled = true;
    };
  }, [segmentId]);

  return resolved.id === segmentId ? resolved.data : LOADING;
}
