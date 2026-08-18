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
 * Chunk hits from /search and /topics/[slug].
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
    <ul className="divide-y divide-[var(--color-border-subtle)]">
      {results.map((result) => (
        <li key={result.chunk_id} className="py-4">
          <p className="text-xs text-[var(--color-ink-muted)]">
            {kindLabel(result.kind)} · سورة {result.surah} · الآيات{" "}
            {result.ayah_start}–{result.ayah_end}
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
              {pendingChunkId === result.chunk_id ? "جارٍ التحميل…" : "تشغيل من هنا"}
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
  );
}
