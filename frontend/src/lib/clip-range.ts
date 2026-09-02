/**
 * Clip range arithmetic — pure, no DOM, no React.
 *
 * The API rejects a clip shorter than one second (API_CONTRACT.md, amendment
 * 9) and a *video* longer than five minutes (amendment 10); an audio export
 * may still run to the end of its segment. The composer never lets the handles
 * reach an invalid range in the first place: every drag is funnelled through
 * these functions and comes back already legal. All values are integer
 * milliseconds (CLAUDE.md rule 5).
 */

import type { ClipOutput } from "@/types/models";

export const MIN_CLIP_MS = 1_000;

/**
 * Ceiling on a video clip, mirroring `clips.models.MAX_VIDEO_SPAN_MS`.
 *
 * Capacity, not policy: a video card is a 1080x1920 H.264 encode with an
 * animated waveform under burned-in subtitles, rendered by two celery workers
 * on a shared two-core host. Audio is a straight AAC transcode and has no
 * ceiling, which is why this is not simply a maximum on `ClipRange`.
 */
export const MAX_VIDEO_CLIP_MS = 5 * 60 * 1_000;

/** Why the API would refuse a span, or null when it would accept it. */
export type SpanProblem = "too-short" | "too-long-for-video";

/** The 400 this span would earn, decided before anyone spends a render. */
export function spanProblem(
  spanMs: number,
  output: ClipOutput
): SpanProblem | null {
  if (spanMs < MIN_CLIP_MS) return "too-short";
  if (output === "video" && spanMs > MAX_VIDEO_CLIP_MS) {
    return "too-long-for-video";
  }
  return null;
}

/** Span a freshly opened composer proposes around the playhead. */
export const DEFAULT_CLIP_MS = 30_000;

export interface ClipRange {
  startMs: number;
  endMs: number;
}

function clamp(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), hi);
}

/**
 * Span bounds available inside a segment.
 *
 * A segment shorter than the minimum cannot produce a legal clip at all; rather
 * than returning an impossible range, the bounds collapse to the whole segment
 * and the caller (ClipComposer) refuses to submit. The maximum is always the
 * segment itself — there is no artificial ceiling.
 */
function spanBounds(totalMs: number): { min: number; max: number } {
  return {
    min: Math.min(MIN_CLIP_MS, totalMs),
    max: Math.max(MIN_CLIP_MS, totalMs),
  };
}

function total(durationMs: number): number {
  return Math.max(0, Math.floor(durationMs));
}

/**
 * Force an arbitrary range inside `[0, durationMs]` and inside the legal span.
 *
 * Ends are swapped if inverted, the span is grown forward to the minimum, and
 * if growing forward would run past the end of the segment the start is pulled
 * back instead.
 */
export function clampClipRange(
  range: ClipRange,
  durationMs: number
): ClipRange {
  const totalMs = total(durationMs);
  const { min, max } = spanBounds(totalMs);

  let start = clamp(Math.round(range.startMs), 0, totalMs);
  let end = clamp(Math.round(range.endMs), 0, totalMs);
  if (end < start) [start, end] = [end, start];

  const span = clamp(end - start, min, max);
  end = start + span;
  if (end > totalMs) {
    end = totalMs;
    start = Math.max(0, end - span);
  }

  return { startMs: start, endMs: end };
}

/**
 * Drag the start handle to `startMs`, holding the end still.
 *
 * The start is confined to `[0, end - min]`, so dragging it past the end
 * handle parks it at the minimum span instead of inverting the range.
 */
export function moveClipStart(
  range: ClipRange,
  startMs: number,
  durationMs: number
): ClipRange {
  const totalMs = total(durationMs);
  const { min } = spanBounds(totalMs);

  const end = clamp(Math.round(range.endMs), min, totalMs);
  const hi = Math.max(0, end - min);

  return { startMs: clamp(Math.round(startMs), 0, hi), endMs: end };
}

/**
 * Drag the end handle to `endMs`, holding the start still.
 *
 * Mirror of {@link moveClipStart}: the end is confined to `[start + min,
 * totalMs]` and never passes the end of the segment.
 */
export function moveClipEnd(
  range: ClipRange,
  endMs: number,
  durationMs: number
): ClipRange {
  const totalMs = total(durationMs);
  const { min } = spanBounds(totalMs);

  const start = clamp(Math.round(range.startMs), 0, Math.max(0, totalMs - min));
  const lo = Math.min(start + min, totalMs);

  return { startMs: start, endMs: clamp(Math.round(endMs), lo, totalMs) };
}

/** The range the composer opens with: DEFAULT_CLIP_MS from the playhead. */
export function defaultClipRange(
  positionMs: number,
  durationMs: number
): ClipRange {
  const totalMs = total(durationMs);
  const start = clamp(Math.round(positionMs), 0, totalMs);
  return clampClipRange(
    { startMs: start, endMs: start + DEFAULT_CLIP_MS },
    totalMs
  );
}

/** Whether a segment is long enough to yield any legal clip at all. */
export function canClipSegment(durationMs: number): boolean {
  return total(durationMs) >= MIN_CLIP_MS;
}
