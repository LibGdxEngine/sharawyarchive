"use client";

import Link from "next/link";
import { useState } from "react";
import { getSegment } from "@/lib/api";
import { useAudioStore } from "@/lib/audio-store";
import { kindLabel } from "@/lib/format";
import type { SearchChunkResult } from "@/types/models";

interface ChunkResultListProps {
  results: SearchChunkResult[];
  /** Shown when `results` is empty. */
  emptyLabel: string;
}

/**
 * The provenance line every consumer of this list inherits.
 *
 * Rule 1 of the project: text that came out of the recogniser is never shown
 * without saying so. On /search these snippets sit directly under authentic
 * Quran text, which makes the distinction the most important thing on the page.
 */
const MACHINE_TRANSCRIPT_NOTE =
  "نتائج من التفريغ الآلي — قد تحتوي على أخطاء";

/**
 * Citation for a chunk: kind, then surah and ayah range when the pipeline was
 * able to place it. An unplaced chunk (null surah/ayahs) prints its kind alone
 * rather than a line with gaps in it.
 */
function citationLine(result: SearchChunkResult): string {
  const parts = [kindLabel(result.kind)];
  if (result.surah !== null) parts.push(`سورة ${result.surah}`);
  if (result.ayah_start !== null && result.ayah_end !== null) {
    parts.push(
      result.ayah_start === result.ayah_end
        ? `الآية ${result.ayah_start}`
        : `الآيات ${result.ayah_start}–${result.ayah_end}`
    );
  }
  return parts.join(" · ");
}

/**
 * Chunk hits from /search, /topics/[slug] and the related-passages rail.
 *
 * The play button resolves the segment's presigned audio URL on demand and
 * hands it to the global store, so audio starts at the matched timestamp
 * without leaving the results. The snippet itself is a link into /listen with
 * the same timestamp for readers who want the full transcript.
 */
export default function ChunkResultList({
  results,
  emptyLabel,
}: ChunkResultListProps) {
  const load = useAudioStore((s) => s.load);
  const [pendingChunkId, setPendingChunkId] = useState<number | null>(null);
  const [failedChunkId, setFailedChunkId] = useState<number | null>(null);

  if (results.length === 0) {
    return <p className="py-8 text-sm text-[var(--color-ink-muted)]">{emptyLabel}</p>;
  }

  const playHere = async (result: SearchChunkResult) => {
    setFailedChunkId(null);
    setPendingChunkId(result.chunk_id);
    try {
      const segment = await getSegment(result.segment_id);
      load(
        {
          segmentId: segment.id,
          title: segment.title,
          audioUrl: segment.audio_url,
          durationMs: segment.duration_ms,
        },
        { startMs: result.start_ms, autoplay: true }
      );
    } catch {
      setFailedChunkId(result.chunk_id);
    } finally {
      setPendingChunkId(null);
    }
  };

  return (
    <>
      <p className="pt-2 text-xs leading-relaxed text-[var(--color-ink-muted)]">
        {MACHINE_TRANSCRIPT_NOTE}
      </p>
      <ul className="divide-y divide-[var(--color-border-subtle)]">
        {results.map((result) => (
          <li key={result.chunk_id} className="py-4">
            <p className="text-xs text-[var(--color-ink-muted)]">
              {citationLine(result)}
            </p>

            <Link
              href={`/listen/${result.segment_id}?t=${result.start_ms}`}
              className="mt-1 block text-base leading-[1.8]"
            >
              {result.text}
            </Link>

            <div className="mt-2 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => playHere(result)}
                disabled={pendingChunkId === result.chunk_id}
                className="rounded border border-[var(--color-border)] px-3 py-1 text-xs text-[var(--color-ink-muted)] disabled:opacity-60"
              >
                {pendingChunkId === result.chunk_id
                  ? "جارٍ التحميل…"
                  : "تشغيل من هنا"}
              </button>
              <span className="truncate text-xs text-[var(--color-ink-faint)]">
                {result.segment_title}
              </span>
              {failedChunkId === result.chunk_id ? (
                <span className="text-xs text-[var(--color-ink-muted)]">
                  تعذّر تشغيل المقطع الآن.
                </span>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}
