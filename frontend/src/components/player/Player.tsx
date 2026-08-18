"use client";

import { useEffect } from "react";
import { useAudioStore } from "@/lib/audio-store";
import type { Track } from "@/lib/audio-store";
import { kindLabel } from "@/lib/format";
import ShareButton from "./ShareButton";
import TranscriptView from "./TranscriptView";
import type { Segment, Transcript } from "@/types/models";

interface PlayerProps {
  segment: Segment;
  transcript: Transcript;
  /** Deep-link position from `?t=`, or null when absent. */
  startMs: number | null;
}

/**
 * Client shell for /listen/[segmentId].
 *
 * Owns nothing about playback itself — the <audio> element and the transport
 * controls live in the root layout, so arriving here (or leaving) never
 * interrupts sound. This component only points the store at this segment and
 * renders the transcript around it.
 */
export default function Player({ segment, transcript, startMs }: PlayerProps) {
  useEffect(() => {
    const store = useAudioStore.getState();
    const track: Track = {
      segmentId: segment.id,
      title: segment.title,
      audioUrl: segment.audio_url,
      durationMs: segment.duration_ms,
    };

    if (store.current !== null && store.current.segmentId === segment.id) {
      // Already the loaded track: honour an explicit deep link, otherwise
      // leave playback exactly where the listener left it.
      if (startMs !== null) store.seekMs(startMs);
      return;
    }

    // `startMs: undefined` makes the store fall back to the saved
    // `pos:<segmentId>` position, so /listen resumes where you stopped.
    store.load(track, {
      startMs: startMs ?? undefined,
      autoplay: false,
    });
  }, [segment, startMs]);

  const ayahRange =
    segment.ayah_start === segment.ayah_end
      ? `الآية ${segment.ayah_start}`
      : `الآيات ${segment.ayah_start}–${segment.ayah_end}`;

  return (
    <article className="reading-column page-shell pt-8">
      <header className="mb-6">
        <p className="text-xs text-[var(--color-ink-muted)]">
          {kindLabel(segment.kind)} · سورة {segment.surah} · {ayahRange}
        </p>
        <h1 className="mt-1 text-2xl font-semibold leading-snug">
          {segment.title}
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <ShareButton segmentId={segment.id} />
          <span className="text-xs text-[var(--color-ink-faint)]">
            {segment.source.title}
          </span>
        </div>
      </header>

      <div className="mb-4 border-y border-[var(--color-border-subtle)] py-3">
        <p className="text-xs leading-relaxed text-[var(--color-ink-muted)]">
          النص مُفرَّغ آليًا وقد يحتوي على أخطاء — نص القرآن الكريم ليس من
          التفريغ الآلي
          {transcript.is_human_reviewed ? (
            <span className="mx-2 inline-block rounded border border-[var(--color-border)] px-1.5 py-0.5 text-[var(--color-ink-faint)]">
              مُراجَع
            </span>
          ) : null}
        </p>
      </div>

      <TranscriptView segmentId={segment.id} words={transcript.words} />

      <p className="mt-6 text-xs text-[var(--color-ink-faint)]">
        عدد الكلمات {transcript.words.length} · إصدار التفريغ{" "}
        {transcript.version} · {transcript.engine}
      </p>
    </article>
  );
}
