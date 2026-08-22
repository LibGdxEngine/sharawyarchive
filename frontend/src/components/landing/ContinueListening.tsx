"use client";

import { useSyncExternalStore } from "react";
import Link from "next/link";
import {
  recentSegmentsSnapshot,
  subscribeRecentSegments,
  type RecentSegment,
} from "@/lib/recent-segments";
import { getSavedPositionMs } from "@/lib/audio-store";

/** Server snapshot and stable empty reference. */
const EMPTY: RecentSegment[] = [];

export default function ContinueListening() {
  const segments = useSyncExternalStore(
    subscribeRecentSegments,
    recentSegmentsSnapshot,
    () => EMPTY
  );

  if (segments.length === 0) return null;

  return (
    <section className="mt-10 w-full max-w-[640px]">
      <h2 className="text-sm font-medium text-[var(--landing-ink-3)]">
        تابع الاستماع
      </h2>
      <ul className="mt-3 space-y-1">
        {segments.slice(0, 4).map((seg) => {
          const savedMs = getSavedPositionMs(seg.segmentId);
          return (
            <li key={seg.segmentId}>
              <Link
                href={`/listen/${seg.segmentId}`}
                className="flex items-center justify-between rounded-lg border border-[var(--landing-chip-border)] px-4 py-2.5 text-sm transition-colors hover:border-[var(--landing-gold-focus)] hover:text-[var(--landing-chip-ink-hover)]"
              >
                <span className="truncate text-[var(--landing-ink-3)]">
                  {seg.title}
                </span>
                {savedMs > 5000 && (
                  <span className="mr-2 shrink-0 text-xs text-[var(--landing-ink-4)]">
                    {formatMinutes(savedMs)}
                  </span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function formatMinutes(ms: number): string {
  const minutes = Math.floor(ms / 60000);
  return `الدقيقة ${minutes}`;
}
