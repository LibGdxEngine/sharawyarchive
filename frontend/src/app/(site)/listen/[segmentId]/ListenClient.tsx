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
    // Skeleton mirrors the loaded layout (meta line, title, action row,
    // transcript lines) so content arriving does not shift the page.
    return (
      <div
        role="status"
        aria-label="جارٍ تحميل المقطع"
        className="reading-column page-shell pt-8"
      >
        <span className="sr-only">جارٍ تحميل المقطع…</span>
        <div aria-hidden className="animate-pulse">
          <div className="h-3 w-40 rounded bg-[var(--color-bg-subtle)]" />
          <div className="mt-2 h-7 w-2/3 rounded bg-[var(--color-bg-subtle)]" />
          <div className="mt-4 flex gap-3">
            <div className="h-6 w-20 rounded bg-[var(--color-bg-subtle)]" />
            <div className="h-6 w-24 rounded bg-[var(--color-bg-subtle)]" />
          </div>
          <div className="mt-6 space-y-3 border-y border-[var(--color-border-subtle)] py-6">
            <div className="h-3 w-full rounded bg-[var(--color-bg-subtle)]" />
            <div className="h-3 w-11/12 rounded bg-[var(--color-bg-subtle)]" />
            <div className="h-3 w-4/5 rounded bg-[var(--color-bg-subtle)]" />
            <div className="h-3 w-full rounded bg-[var(--color-bg-subtle)]" />
            <div className="h-3 w-2/3 rounded bg-[var(--color-bg-subtle)]" />
          </div>
        </div>
      </div>
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
