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
 * Segment metadata + transcript for /listen.
 *
 * The route server-renders both and hands them in as `initialSegment` /
 * `initialTranscript`, so the first paint costs no round trip at all. The
 * browser then fetches them again anyway, which is not redundant:
 *
 *  1. The service worker only sees requests its clients make. A transcript
 *     fetched on the server never passes through the stale-while-revalidate
 *     route, so it is never in the runtime cache when the network goes away.
 *  2. Navigations are network-first with a cache fallback, so the document
 *     that carried `initialSegment` may itself be a replay — and its presigned
 *     `audio_url` is good for six hours, not forever.
 *  3. When the network is already gone, the copies saved by
 *     `saveSegmentOffline` are right here to fall back to.
 *
 * The presigned `audio_url` in a cached segment has long expired; playback of a
 * saved segment goes through `getOfflineAudioUrl` instead.
 */
const LOADING: SegmentData = { status: "loading" };

/**
 * The server's copy, or `loading` where it could not supply a complete one.
 *
 * A missing transcript is only rendered when the segment says there is none to
 * have: `Player` reports a null transcript as "not transcribed yet", and a
 * fetch that merely failed must not be shown to the reader as an editorial
 * fact about the archive. In that case the browser's own fetch fills it in.
 */
function seed(
  segment: Segment | null,
  transcript: Transcript | null
): SegmentData {
  if (segment === null) return LOADING;
  if (transcript === null && segment.transcript_version !== null) return LOADING;
  return { status: "ready", segment, transcript, source: "network" };
}

export function useSegmentData(
  segmentId: number,
  initialSegment: Segment | null = null,
  initialTranscript: Transcript | null = null
): SegmentData {
  // The id is kept next to the data so that a change of segment reads from the
  // incoming props during render, rather than through an effect that resets
  // state — see the return statement.
  const [resolved, setResolved] = useState<{ id: number; data: SegmentData }>(
    () => ({ id: segmentId, data: seed(initialSegment, initialTranscript) })
  );

  // Only these two are read by the effect, and both are primitives: depending
  // on the prop objects themselves would refetch on every RSC payload.
  const hasInitial = initialSegment !== null;
  const knownVersion = initialSegment?.transcript_version ?? null;

  useEffect(() => {
    let cancelled = false;

    const fromNetwork = async (): Promise<SegmentData> => {
      // The version is only a cache key — the endpoint always serves the
      // latest — so knowing it up front is what lets the two requests run at
      // once instead of the transcript waiting on the segment.
      const [segment, transcript] = await Promise.all([
        getSegment(segmentId),
        knownVersion === null ? null : getTranscript(segmentId, knownVersion),
      ]);

      if (segment.transcript_version === null) {
        // Ingested but not yet transcribed: playable, honestly untranscribed.
        return { status: "ready", segment, transcript: null, source: "network" };
      }
      // Either we had no version to ask with, or a correction was approved
      // between the render and now and the one we asked with is stale.
      const current =
        transcript !== null && transcript.version === segment.transcript_version
          ? transcript
          : await getTranscript(segmentId, segment.transcript_version);

      return { status: "ready", segment, transcript: current, source: "network" };
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
      // A failed refetch must not blank out a page the server already filled:
      // the saved copy is a fallback for having nothing, not for having this.
      if (cancelled) return;
      if (next.status === "error" && hasInitial) return;
      setResolved({ id: segmentId, data: next });
    })();

    return () => {
      cancelled = true;
    };
  }, [segmentId, hasInitial, knownVersion]);

  // On a client-side navigation the state still describes the previous
  // segment, but the new one's server-rendered copy is already in props — so
  // fall back to that rather than flashing the skeleton for a round trip.
  return resolved.id === segmentId
    ? resolved.data
    : seed(initialSegment, initialTranscript);
}
