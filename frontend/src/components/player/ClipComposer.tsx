"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import ClipOutputPicker from "@/components/clip/ClipOutputPicker";
import ClipOverviewStrip from "@/components/clip/ClipOverviewStrip";
import ClipPresetPicker from "@/components/clip/ClipPresetPicker";
import ClipPreview, {
  CLIP_THEMES,
  CLIP_THEME_PRESET,
} from "@/components/clip/ClipPreview";
import type { ClipTheme } from "@/components/clip/ClipPreview";
import ClipResult from "@/components/clip/ClipResult";
import ClipTimeField from "@/components/clip/ClipTimeField";
import ClipWordPicker from "@/components/clip/ClipWordPicker";
import { readPlayheadMs, usePlayheadMs } from "@/components/clip/usePlayhead";
import { useRangePlayback } from "@/components/clip/useRangePlayback";
import { useActiveWordIndex } from "@/components/player/useActiveWord";
import { useClipRender } from "@/components/player/useClipRender";
import { useLoadTrack } from "@/components/player/useLoadTrack";
import {
  MAX_VIDEO_CLIP_MS,
  MIN_CLIP_MS,
  canClipSegment,
  defaultClipRange,
  spanProblem,
} from "@/lib/clip-range";
import { formatMs } from "@/lib/format";
import {
  moveTrimEnd,
  moveTrimStart,
  nearestWordIndex,
  trimFromTimes,
  trimTimesMs,
} from "@/lib/word-trim";
import type { WordTrim } from "@/lib/word-trim";
import type {
  ClipOutput,
  Segment,
  TranscriptWord,
  Waveform,
} from "@/types/models";

interface ClipComposerProps {
  segment: Segment;
  /** Word-level transcript — the unit the trim is expressed in. */
  words: TranscriptWord[];
  /** Closes an embedding surface (the standalone page has no such bar). */
  onClose?: () => void;
}

/** Ready-made spans, measured forward from the current start. */
const QUICK_SPANS_MS = [15_000, 30_000, 60_000] as const;

/**
 * "مقطع للمشاركة" — the clip composer.
 *
 * The range is chosen by pointing at WORDS, with the waveform demoted to an
 * overview strip you navigate with. The old picker put both trim handles on a
 * waveform of 800 buckets: over an 84-minute segment that is ~25 seconds per
 * drawn bar, so a 30-second selection was one bar wide and the two handles
 * landed on the same pixel with only the top one grabbable. Words are the right
 * unit anyway — what gets clipped is a sentence, not an interval.
 *
 * Shown as a standalone page at `/listen/[segmentId]/clip`; `onClose` turns the
 * cancel action into a back button when the composer is embedded somewhere
 * that can return.
 */
export default function ClipComposer({
  segment,
  words,
  onClose,
}: ClipComposerProps) {
  const durationMs = segment.duration_ms;
  const clippable = canClipSegment(durationMs) && words.length > 0;

  // Opened from the listen page, the track is usually already loaded; opened
  // by URL it is not, and the preview button would have nothing to play.
  useLoadTrack(segment, null);

  const [trim, setTrim] = useState<WordTrim>(() =>
    trimFromTimes(
      words,
      defaultClipRange(readPlayheadMs(segment.id), durationMs)
    )
  );
  const [theme, setTheme] = useState<ClipTheme>(CLIP_THEMES[0]);
  const [output, setOutput] = useState<ClipOutput>("video");
  const [scrollTo, setScrollTo] = useState<{ index: number } | null>(null);

  // null = still loading, [] = unavailable (the strip degrades to a plain axis).
  const [peaks, setPeaks] = useState<number[] | null>(null);

  const render = useClipRender();
  const { activeRange, playRange, stop } = useRangePlayback(segment.id);
  const activeWordIndex = useActiveWordIndex(segment.id, words);
  const playheadMs = usePlayheadMs(segment.id);

  const range = useMemo(
    () => (clippable ? trimTimesMs(words, trim) : { startMs: 0, endMs: 0 }),
    [clippable, words, trim]
  );
  const spanMs = range.endMs - range.startMs;
  const problem = spanProblem(spanMs, output);

  // ---- waveform -----------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      try {
        const response = await fetch(segment.waveform_url, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(String(response.status));
        const data = (await response.json()) as Waveform;
        if (cancelled) return;
        setPeaks(Array.isArray(data.peaks) ? data.peaks : []);
      } catch {
        // Usually the bucket's CORS policy, not a missing file. The strip
        // draws a plain time axis and everything else still works.
        if (!cancelled) setPeaks([]);
      }
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [segment.waveform_url]);

  // ---- moving the trim ----------------------------------------------------
  const setStartMs = (ms: number): void =>
    setTrim((previous) =>
      moveTrimStart(words, previous, nearestWordIndex(words, ms))
    );
  const setEndMs = (ms: number): void =>
    setTrim((previous) =>
      moveTrimEnd(words, previous, nearestWordIndex(words, ms))
    );

  const scrub = (ms: number): void => {
    // Navigation, not selection: move the listening position and bring the
    // matching part of the transcript into view. The trim stays put.
    const index = nearestWordIndex(words, ms);
    if (index >= 0) setScrollTo({ index });
  };

  const captureStart = (): void => setStartMs(readPlayheadMs(segment.id));
  const captureEnd = (): void => setEndMs(readPlayheadMs(segment.id));

  const quickSpan = (ms: number): void =>
    setTrim(trimFromTimes(words, { startMs: range.startMs, endMs: range.startMs + ms }));

  // ---- submit -------------------------------------------------------------
  const submit = (): void =>
    render.submit({
      segment_id: segment.id,
      start_ms: range.startMs,
      end_ms: range.endMs,
      preset: CLIP_THEME_PRESET[theme.id],
      output,
    });

  if (!clippable) {
    return (
      <section
        aria-label="إنشاء مقطع للمشاركة"
        className="mt-4 basis-full border-t border-[var(--lp-card-border)] pt-4"
      >
        <p className="text-sm text-[var(--color-ink-muted)]">
          هذا المقطع أقصر من {MIN_CLIP_MS / 1000} ثانية، ولا يمكن اقتطاع مقطع
          منه.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="إنشاء مقطع للمشاركة"
      className="mt-4 basis-full border-t border-[var(--lp-card-border)] pt-4"
    >
      {/* ---- overview: where you are in the whole segment ---------------- */}
      <ClipOverviewStrip
        durationMs={durationMs}
        peaks={peaks ?? []}
        range={range}
        playheadMs={playheadMs}
        onScrub={scrub}
      />

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <ClipTimeField label="من" valueMs={range.startMs} onCommit={setStartMs} />
        <ClipTimeField label="إلى" valueMs={range.endMs} onCommit={setEndMs} />
        <p
          role="status"
          aria-live="polite"
          className="text-xs text-[var(--color-ink-muted)]"
        >
          المدة {formatMs(spanMs)}
          {problem === "too-short"
            ? ` — الحد الأدنى ${MIN_CLIP_MS / 1000} ثانية`
            : problem === "too-long-for-video"
              ? ` — أقصى مدة للفيديو ${MAX_VIDEO_CLIP_MS / 60_000} دقائق؛ اختر «صوت فقط» لمقطع أطول`
              : ""}
        </p>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() =>
            activeRange !== null ? stop() : playRange(range)
          }
          className="listen-chip"
        >
          {activeRange !== null ? "إيقاف المعاينة" : "استمع للتحديد"}
        </button>
        <button
          type="button"
          onClick={captureStart}
          className="min-h-11 rounded-lg border border-[var(--color-border)] px-3 text-xs text-[var(--color-ink-muted)]"
        >
          بداية من الموضع
        </button>
        <button
          type="button"
          onClick={captureEnd}
          className="min-h-11 rounded-lg border border-[var(--color-border)] px-3 text-xs text-[var(--color-ink-muted)]"
        >
          نهاية عند الموضع
        </button>
        {QUICK_SPANS_MS.map((ms) => (
          <button
            key={ms}
            type="button"
            onClick={() => quickSpan(ms)}
            className="min-h-11 rounded-lg border border-[var(--color-border)] px-3 text-xs text-[var(--color-ink-muted)]"
          >
            {ms / 1000} ثانية
          </button>
        ))}
      </div>

      {/* ---- the picker itself, beside a live card ---------------------- */}
      <div className="mt-2 flex flex-wrap gap-6">
        <div className="min-w-[280px] flex-1">
          <p className="text-xs text-[var(--color-ink-faint)]">
            اضغط كلمةً لتحريك أقرب حدّ، أو اسحب المقبضين — القصّ يتبع الكلمات، لا
            الموجة الصوتية.
          </p>
          <ClipWordPicker
            words={words}
            trim={trim}
            setTrim={setTrim}
            activeWordIndex={activeWordIndex}
            scrollTo={scrollTo}
          />
        </div>

        {output === "video" ? (
          <div className="mx-auto shrink-0">
            <ClipPreview
              words={words}
              trim={trim}
              theme={theme}
              // This page has no ayah alignment — that lives on the verse
              // page's InterleavedTranscript. Every word here is machine
              // transcript, and the card renders it as such.
              isQuranWord={() => false}
              activeWordIndex={activeWordIndex}
            />
          </div>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap gap-8">
        <ClipOutputPicker output={output} setOutput={setOutput} />
        {output === "video" ? (
          <ClipPresetPicker theme={theme} setTheme={setTheme} />
        ) : null}
      </div>

      {/* ---- submit + status ------------------------------------------- */}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={submit}
          disabled={problem !== null || render.busy}
          className="listen-chip"
        >
          {render.creating
            ? "جارٍ الإرسال…"
            : render.clip !== null && !render.busy
              ? "أعد المحاولة"
              : output === "audio"
                ? "إنشاء الصوت"
                : "إنشاء الفيديو"}
        </button>
        {onClose !== undefined ? (
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-[var(--color-ink-muted)]"
          >
            إلغاء
          </button>
        ) : (
          <Link
            href={`/listen/${segment.id}`}
            className="text-sm text-[var(--color-ink-muted)] underline underline-offset-4"
          >
            العودة إلى الاستماع
          </Link>
        )}
        {render.message !== "" ? (
          <span role="status" className="text-xs text-[var(--color-ink-muted)]">
            {render.message}
          </span>
        ) : null}
      </div>

      {render.clip !== null ? (
        <ClipResult
          clip={render.clip}
          segmentId={segment.id}
          timedOut={render.timedOut}
        />
      ) : null}
    </section>
  );
}
