"use client";

import { useEffect, useMemo, useState } from "react";
import ErrorNote from "@/components/ErrorNote";
import { useSegmentData } from "@/components/player/useSegmentData";
import { useLoadTrack } from "@/components/player/useLoadTrack";
import { getAyah } from "@/lib/api";
import { normalizeForIndex } from "@/lib/arabic";
import {
  MAX_INTERLEAVE_AYAHS,
  buildVerseBlocks,
  matchAyahsInTranscript,
} from "@/lib/ayah-match";
import type { AyahRef } from "@/lib/ayah-match";
import { formatMs, kindLabel, toArabicIndic } from "@/lib/format";
import AyahCard from "./AyahCard";
import InterleavedTranscript from "./InterleavedTranscript";
import SegmentSwitcher from "./SegmentSwitcher";
import type { Segment, SegmentSummary, Transcript } from "@/types/models";

interface VersePlayerProps {
  surah: number;
  ayahNumber: number;
  focusAyah: AyahRef;
  segments: SegmentSummary[];
  segmentId: number;
  /** Deep-link position from `?t=`, or null. */
  startMs: number | null;
  surahName: string | null;
  onSelectSegment(id: number): void;
}

/** "الآية ٢٨" or "الآيات ٢٧–٢٩" — Arabic-Indic, this is Quranic numbering. */
function ayahRangeLabel(start: number, end: number): string {
  return start === end
    ? `الآية ${toArabicIndic(start)}`
    : `الآيات ${toArabicIndic(start)}–${toArabicIndic(end)}`;
}

/**
 * The player column of the verse page: loads the covering segment and its
 * transcript in the browser (service-worker visible, offline capable), then
 * hands the interleaved article its blocks.
 */
export default function VersePlayer(props: VersePlayerProps) {
  const data = useSegmentData(props.segmentId);

  if (data.status === "loading") {
    return (
      <p role="status" className="pt-6 text-sm text-[var(--color-ink-muted)]">
        جارٍ تحميل المقطع…
      </p>
    );
  }

  if (data.status === "error") {
    return (
      <div className="pt-6">
        <ErrorNote>
          تعذّر تحميل هذا المقطع الآن. حاول مرة أخرى بعد قليل.
        </ErrorNote>
      </div>
    );
  }

  return (
    // Keyed by segment: switching segments remounts the body, so its
    // range-ayah fetch state starts clean instead of going stale.
    <VersePlayerBody
      key={data.segment.id}
      {...props}
      segment={data.segment}
      transcript={data.transcript}
    />
  );
}

interface VersePlayerBodyProps extends VersePlayerProps {
  segment: Segment;
  transcript: Transcript | null;
}

function VersePlayerBody({
  surah,
  ayahNumber,
  focusAyah,
  segments,
  startMs,
  surahName,
  onSelectSegment,
  segment,
  transcript,
}: VersePlayerBodyProps) {
  useLoadTrack(segment, startMs);

  // Verified text for every ayah the segment covers — the matcher's needles.
  // Over the interleave cap nothing is fetched: the `?? [focusAyah]` fallback
  // below is the honest minimum there and on any fetch failure.
  const [rangeAyahs, setRangeAyahs] = useState<AyahRef[] | null>(null);
  useEffect(() => {
    const span = segment.ayah_end - segment.ayah_start + 1;
    if (span < 1 || span > MAX_INTERLEAVE_AYAHS) return;
    let cancelled = false;
    void (async () => {
      try {
        const details = await Promise.all(
          Array.from({ length: span }, (_, k) =>
            getAyah(surah, segment.ayah_start + k)
          )
        );
        if (cancelled) return;
        setRangeAyahs(
          details.map((detail) => ({
            number: detail.number,
            textUthmani: detail.text_uthmani,
          }))
        );
      } catch {
        // The `?? [focusAyah]` fallback below is the honest minimum.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [segment, surah, focusAyah]);

  const words = useMemo(() => transcript?.words ?? [], [transcript]);
  // A transcript whose words never got aligned is indistinguishable from no
  // transcript for this page — everything below renders from the word spans.
  const hasWords = transcript !== null && words.length > 0;
  const ayahRefs = useMemo(
    () => rangeAyahs ?? [focusAyah],
    [rangeAyahs, focusAyah]
  );

  const matches = useMemo(
    () =>
      words.length > 0
        ? matchAyahsInTranscript(ayahRefs, words, normalizeForIndex)
        : [],
    [ayahRefs, words]
  );
  const blocks = useMemo(
    () => buildVerseBlocks(words, ayahRefs, matches, ayahNumber),
    [words, ayahRefs, matches, ayahNumber]
  );

  return (
    <>
      <header>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-bold leading-snug [font-family:var(--font-amiri)] sm:text-3xl">
            {segment.title}
          </h1>
          <span className="whitespace-nowrap rounded-full bg-[var(--verse-badge-bg)] px-3 py-1 text-xs font-semibold text-[var(--verse-deep)]">
            {kindLabel(segment.kind)}{" "}
            {ayahRangeLabel(segment.ayah_start, segment.ayah_end)}
          </span>
        </div>
        <p className="mt-2 text-sm text-[var(--color-ink-faint)]">
          {segment.source.title} · المدة{" "}
          <span dir="ltr" className="tabular-nums">
            {formatMs(segment.duration_ms)}
          </span>{" "}
          · النسخ الآلي قابل للمراجعة
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs text-[var(--color-ink-muted)]">
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="h-2.5 w-2.5 rounded-[3px] bg-[var(--verse-gold)]"
            />
            آية موثّقة
          </span>
          <span className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              className="h-2.5 w-2.5 rounded-[3px] border border-[var(--verse-card-border)] bg-[var(--verse-card-bg)]"
            />
            نسخ آلي
          </span>
          {transcript?.is_human_reviewed ? (
            <span className="rounded border border-[var(--color-border)] px-1.5 py-0.5 text-[var(--color-ink-faint)]">
              مُراجَع
            </span>
          ) : null}
        </div>

        <SegmentSwitcher
          segments={segments}
          currentId={segment.id}
          onSelect={onSelectSegment}
        />

        {hasWords ? (
          <p className="mt-5 inline-flex items-center gap-2.5 rounded-[10px] border border-[var(--verse-hint-border)] bg-[var(--verse-card-bg)] px-4 py-2.5 text-sm text-[var(--verse-deep)]">
            <span aria-hidden="true" className="text-[var(--verse-gold)]">
              ✦
            </span>
            ظلِّل أيَّ جملةٍ بالسحب — لتشغيلها، أو إنشاء مقطعٍ منها، أو نسخ
            رابط لحظتها.
          </p>
        ) : null}

        <div className="mt-5 border-y border-[var(--color-border-subtle)] py-3">
          <p className="text-xs leading-relaxed text-[var(--color-ink-muted)]">
            النص مُفرَّغ آليًا وقد يحتوي على أخطاء — نص القرآن الكريم ليس من
            التفريغ الآلي
          </p>
        </div>
      </header>

      <div className="mt-4">
        {hasWords ? (
          <InterleavedTranscript
            segment={segment}
            words={words}
            blocks={blocks}
            surahName={surahName}
          />
        ) : (
          <>
            <AyahCard
              ayah={focusAyah}
              match={null}
              activeWordIndex={-1}
              surahName={surahName}
              surahNumber={surah}
            />
            <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
              لم يُفرَّغ هذا المقطع بعد — التفريغ الآلي قيد الإعداد. يمكنك
              الاستماع الآن، وسيظهر النص مع إبراز الكلمات فور اكتماله.
            </p>
          </>
        )}
      </div>
    </>
  );
}
