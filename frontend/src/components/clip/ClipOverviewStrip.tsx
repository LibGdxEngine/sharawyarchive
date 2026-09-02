"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { formatMs } from "@/lib/format";
import type { ClipRange } from "@/lib/clip-range";

interface ClipOverviewStripProps {
  durationMs: number;
  /** Waveform peaks, or `[]` when the JSON could not be fetched. */
  peaks: readonly number[];
  /** The chosen span, drawn as a lens. */
  range: ClipRange;
  /** Live playback position. */
  playheadMs: number;
  /** A place in the segment was picked — seek there and scroll the word list. */
  onScrub(ms: number): void;
}

/** Bars drawn, however many buckets the JSON carries. */
const MAX_BARS = 240;

/** Keyboard scrub step; Shift takes a minute at a time. */
const STEP_MS = 10_000;
const COARSE_STEP_MS = 60_000;

/** Peak buckets reduced to at most MAX_BARS, keeping the loudest of each group. */
function toBars(peaks: readonly number[]): number[] {
  if (peaks.length <= MAX_BARS) return [...peaks];
  const groupSize = peaks.length / MAX_BARS;
  const bars: number[] = [];
  for (let bar = 0; bar < MAX_BARS; bar += 1) {
    const from = Math.floor(bar * groupSize);
    const to = Math.min(peaks.length, Math.floor((bar + 1) * groupSize));
    let loudest = 0;
    for (let i = from; i < to; i += 1) loudest = Math.max(loudest, peaks[i]);
    bars.push(loudest);
  }
  return bars;
}

/**
 * Where you are in the whole segment — navigation, not selection.
 *
 * The strip deliberately does NOT carry the trim handles any more. At 800
 * buckets over 84 minutes one drawn bar is ~25 seconds, so a 30-second
 * selection was about one bar wide and both handles landed on the same pixel.
 * Precision now lives in the word list; this is the map that gets you to the
 * right part of it.
 *
 * The axis runs left-to-right inside the RTL page. That is not a per-component
 * RTL hack (CLAUDE.md rule 3): it is a time axis, the same one the media
 * element's own progress bar uses, and it carries no text to mirror.
 */
export default function ClipOverviewStrip({
  durationMs,
  peaks,
  range,
  playheadMs,
  onScrub,
}: ClipOverviewStripProps) {
  const bars = useMemo(() => toBars(peaks), [peaks]);
  const trackRef = useRef<HTMLDivElement>(null);
  const [scrubbing, setScrubbing] = useState(false);

  const msFromClientX = useCallback(
    (clientX: number): number => {
      const element = trackRef.current;
      if (element === null) return 0;
      const rect = element.getBoundingClientRect();
      if (rect.width === 0) return 0;
      const ratio = (clientX - rect.left) / rect.width;
      return Math.round(Math.min(Math.max(ratio, 0), 1) * durationMs);
    },
    [durationMs]
  );

  const percent = (ms: number) =>
    durationMs === 0 ? 0 : Math.min(100, Math.max(0, (ms / durationMs) * 100));

  const release = (event: React.PointerEvent<HTMLDivElement>): void => {
    setScrubbing(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  return (
    <div
      ref={trackRef}
      role="slider"
      tabIndex={0}
      dir="ltr"
      aria-label="التنقّل داخل المقطع"
      aria-valuemin={0}
      aria-valuemax={durationMs}
      aria-valuenow={playheadMs}
      aria-valuetext={formatMs(playheadMs)}
      onPointerDown={(event) => {
        event.preventDefault();
        setScrubbing(true);
        event.currentTarget.setPointerCapture(event.pointerId);
        onScrub(msFromClientX(event.clientX));
      }}
      onPointerMove={(event) => {
        if (!scrubbing) return;
        onScrub(msFromClientX(event.clientX));
      }}
      onPointerUp={release}
      onPointerCancel={release}
      onLostPointerCapture={() => setScrubbing(false)}
      onKeyDown={(event) => {
        const step = event.shiftKey ? COARSE_STEP_MS : STEP_MS;
        // A time axis, so the arrows follow the axis, not the script.
        if (event.key === "ArrowRight") {
          event.preventDefault();
          onScrub(Math.min(durationMs, playheadMs + step));
        } else if (event.key === "ArrowLeft") {
          event.preventDefault();
          onScrub(Math.max(0, playheadMs - step));
        } else if (event.key === "Home") {
          event.preventDefault();
          onScrub(0);
        } else if (event.key === "End") {
          event.preventDefault();
          onScrub(durationMs);
        }
      }}
      className="relative h-14 w-full cursor-pointer touch-none select-none rounded border border-[var(--lp-card-border)] bg-[var(--color-bg-subtle)]"
    >
      {bars.length > 0 ? (
        <svg
          viewBox={`0 0 ${bars.length} 100`}
          preserveAspectRatio="none"
          className="h-full w-full"
          aria-hidden="true"
        >
          {bars.map((peak, index) => {
            const height = Math.max(2, peak * 100);
            return (
              <rect
                key={index}
                x={index + 0.15}
                y={(100 - height) / 2}
                width={0.7}
                height={height}
                fill="var(--color-ink-faint)"
              />
            );
          })}
        </svg>
      ) : (
        // No peaks — usually the waveform JSON could not be fetched. A plain
        // axis still navigates; the old code fell back to two stacked range
        // sliders, which navigated nothing.
        <div aria-hidden="true" className="h-full w-full">
          <span className="absolute inset-x-0 top-1/2 h-px bg-[var(--color-ink-faint)]" />
        </div>
      )}

      {/* The lens: where the selection sits inside the whole segment. */}
      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 border-x-2 border-[var(--color-accent)] bg-[var(--color-accent)]/20"
        style={{
          left: `${percent(range.startMs)}%`,
          width: `${Math.max(
            0.5,
            percent(range.endMs) - percent(range.startMs)
          )}%`,
        }}
      />

      <span
        aria-hidden="true"
        className="pointer-events-none absolute inset-y-0 w-px bg-[var(--color-ink)]"
        style={{ left: `${percent(playheadMs)}%` }}
      />
    </div>
  );
}
