"use client";

import { useState } from "react";
import VersePlayer from "@/components/verse/VersePlayer";
import type { AyahRef } from "@/lib/ayah-match";
import type { SegmentSummary } from "@/types/models";

interface VersePageClientProps {
  surah: number;
  ayahNumber: number;
  focusAyah: AyahRef;
  segments: SegmentSummary[];
  initialSegmentId: number;
  /** Deep-link position from `?t=`, or null when absent. */
  startMs: number | null;
  surahName: string | null;
}

/**
 * Owns the selected segment for the verse page. The server picks the initial
 * one (?seg= or the first covering segment); switching via SegmentSwitcher
 * stays client-side, with the id written back to ?seg= so the URL remains
 * shareable at the chosen segment.
 */
export default function VersePageClient({
  surah,
  ayahNumber,
  focusAyah,
  segments,
  initialSegmentId,
  startMs,
  surahName,
}: VersePageClientProps) {
  const [selectedId, setSelectedId] = useState(initialSegmentId);

  const segmentId = segments.some((entry) => entry.id === selectedId)
    ? selectedId
    : initialSegmentId;

  const selectSegment = (id: number) => {
    setSelectedId(id);
    const url = new URL(window.location.href);
    url.searchParams.set("seg", String(id));
    window.history.replaceState(null, "", url.toString());
  };

  return (
    <VersePlayer
      surah={surah}
      ayahNumber={ayahNumber}
      focusAyah={focusAyah}
      segments={segments}
      segmentId={segmentId}
      // The ?t= deep link belongs to the segment it arrived with; switching
      // segments must not replay it on the new track.
      startMs={segmentId === initialSegmentId ? startMs : null}
      surahName={surahName}
      onSelectSegment={selectSegment}
    />
  );
}
