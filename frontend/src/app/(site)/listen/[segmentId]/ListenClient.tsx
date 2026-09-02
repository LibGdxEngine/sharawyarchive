"use client";

import ErrorNote from "@/components/ErrorNote";
import ListenSkeleton from "@/components/player/ListenSkeleton";
import Player from "@/components/player/Player";
import { useSegmentData } from "@/components/player/useSegmentData";
import type { Segment, Transcript } from "@/types/models";

interface ListenClientProps {
  segmentId: number;
  /** Deep-link position from `?t=`, or null when absent. */
  startMs: number | null;
  /** Server-rendered segment, or null where the API could not answer. */
  initialSegment: Segment | null;
  /** Server-rendered transcript; null when absent or not yet transcribed. */
  initialTranscript: Transcript | null;
}

/**
 * Data shell for /listen/[segmentId].
 *
 * Renders the server's copy of the segment immediately, then lets
 * `useSegmentData` refetch in the browser — see that hook for why the second
 * request is the difference between a page that survives losing the network
 * and one that does not.
 */
export default function ListenClient({
  segmentId,
  startMs,
  initialSegment,
  initialTranscript,
}: ListenClientProps) {
  const data = useSegmentData(segmentId, initialSegment, initialTranscript);

  if (data.status === "loading") {
    return <ListenSkeleton />;
  }

  if (data.status === "error") {
    return (
      <div className="reading-column page-shell">
        <ErrorNote>
          تعذّر تحميل هذا المقطع الآن. حاول مرة أخرى بعد قليل.
        </ErrorNote>
      </div>
    );
  }

  return (
    <Player
      segment={data.segment}
      transcript={data.transcript}
      startMs={startMs}
    />
  );
}
