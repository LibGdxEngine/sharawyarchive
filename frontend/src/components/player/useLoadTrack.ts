"use client";

import { useEffect } from "react";
import { useAudioStore } from "@/lib/audio-store";
import type { Track } from "@/lib/audio-store";
import { getOfflineAudioUrl } from "@/lib/offline";
import type { Segment } from "@/types/models";

/**
 * Point the global audio store at `segment` — extracted verbatim from the
 * /listen Player so the verse page loads tracks with identical semantics:
 * offline copy preferred over the presigned URL, `?t=` deep links seek and
 * autoplay, and anything else resumes from the saved position.
 */
export function useLoadTrack(segment: Segment, startMs: number | null): void {
  useEffect(() => {
    let cancelled = false;

    void (async () => {
      // A saved segment plays from Cache Storage. The presigned URL is the
      // fallback, not the other way round: offline it is unreachable, and it
      // has an expiry even when there is a network.
      const offlineUrl = await getOfflineAudioUrl(segment.id);
      const store = useAudioStore.getState();

      // Whoever ends up not putting this URL into a track has to free it; the
      // store frees the ones that do get used, when it replaces the track.
      const discardOfflineUrl = () => {
        if (offlineUrl !== null) URL.revokeObjectURL(offlineUrl);
      };

      if (cancelled) {
        discardOfflineUrl();
        return;
      }

      if (store.current !== null && store.current.segmentId === segment.id) {
        // Already the loaded track: honour an explicit deep link, otherwise
        // leave playback exactly where the listener left it.
        discardOfflineUrl();
        if (startMs !== null) {
          store.seekMs(startMs);
          store.play();
        }
        return;
      }

      const track: Track = {
        segmentId: segment.id,
        title: segment.title,
        audioUrl: offlineUrl ?? segment.audio_url,
        durationMs: segment.duration_ms,
      };

      // `startMs: undefined` makes the store fall back to the saved
      // `pos:<segmentId>` position, so the page resumes where you stopped.
      // A `?t=` deep link, by contrast, is a request to hear that moment —
      // so it starts playing (subject to the browser's autoplay policy).
      store.load(track, {
        startMs: startMs ?? undefined,
        autoplay: startMs !== null,
      });
    })();

    return () => {
      cancelled = true;
    };
  }, [segment, startMs]);
}
