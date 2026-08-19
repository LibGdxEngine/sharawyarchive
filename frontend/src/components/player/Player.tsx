"use client";

import { useEffect } from "react";
import { useAudioStore } from "@/lib/audio-store";
import type { Track } from "@/lib/audio-store";
import { kindLabel } from "@/lib/format";
import { getOfflineAudioUrl } from "@/lib/offline";
import ShareButton from "./ShareButton";
import ClipComposer from "./ClipComposer";
import OfflineButton from "./OfflineButton";
import RelatedPassages from "./RelatedPassages";
import TranscriptView from "./TranscriptView";
import type { Segment, Transcript } from "@/types/models";

interface PlayerProps {
  segment: Segment;
  /** Null when the segment has not been transcribed yet. */
  transcript: Transcript | null;
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
      // `pos:<segmentId>` position, so /listen resumes where you stopped.
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
          {/* Clip karaoke and offline saving both need transcript words. */}
          {transcript !== null ? (
            <ClipComposer key={segment.id} segment={segment} />
          ) : null}
          <span className="text-xs text-[var(--color-ink-faint)]">
            {segment.source.title}
          </span>
        </div>
      </header>

      {transcript !== null ? (
        <>
          <div className="mb-4 border-y border-[var(--color-border-subtle)] py-3">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <p className="text-xs leading-relaxed text-[var(--color-ink-muted)]">
                النص مُفرَّغ آليًا وقد يحتوي على أخطاء — نص القرآن الكريم ليس من
                التفريغ الآلي
                {transcript.is_human_reviewed ? (
                  <span className="mx-2 inline-block rounded border border-[var(--color-border)] px-1.5 py-0.5 text-[var(--color-ink-faint)]">
                    مُراجَع
                  </span>
                ) : null}
              </p>
              <OfflineButton key={segment.id} segment={segment} />
            </div>
          </div>

          <TranscriptView segmentId={segment.id} words={transcript.words} />

          <p className="mt-6 text-xs text-[var(--color-ink-faint)]">
            عدد الكلمات {transcript.words.length} · إصدار التفريغ{" "}
            {transcript.version} · {transcript.engine}
          </p>
        </>
      ) : (
        <div className="mb-4 border-y border-[var(--color-border-subtle)] py-6">
          <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
            لم يُفرَّغ هذا المقطع بعد — التفريغ الآلي قيد الإعداد. يمكنك
            الاستماع الآن، وسيظهر النص مع إبراز الكلمات فور اكتماله.
          </p>
        </div>
      )}

      <RelatedPassages key={segment.id} segmentId={segment.id} />
    </article>
  );
}
