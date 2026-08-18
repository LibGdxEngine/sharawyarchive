"use client";

import ErrorNote from "@/components/ErrorNote";
import Player from "@/components/player/Player";
import { useSegmentData } from "@/components/player/useSegmentData";

interface ListenClientProps {
  segmentId: number;
  /** Deep-link position from `?t=`, or null when absent. */
  startMs: number | null;
}

/**
 * Data shell for /listen/[segmentId].
 *
 * The segment and its transcript are fetched here, in the browser, rather than
 * on the server — see `useSegmentData` for why that is the difference between
 * a page that survives losing the network and one that does not.
 */
export default function ListenClient({
  segmentId,
  startMs,
}: ListenClientProps) {
  const data = useSegmentData(segmentId);

  if (data.status === "loading") {
    return (
      <p
        role="status"
        className="reading-column page-shell pt-8 text-sm text-[var(--color-ink-muted)]"
      >
        جارٍ تحميل المقطع…
      </p>
    );
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
