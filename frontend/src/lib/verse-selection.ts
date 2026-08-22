/**
 * Drag-selection over transcript words — pure state machine, no DOM.
 *
 * The verse page lets the reader sweep a run of words with the pointer (or
 * close a range with shift-clicks) and act on it: play it, clip it, or copy a
 * moment link. This module owns only the arithmetic; the pointer wiring lives
 * in components/verse/InterleavedTranscript.tsx.
 *
 * Reuses `WordRange` from correction-selection so downstream consumers
 * (rangeText, the clip trim) speak one range type.
 */

import type { WordRange } from "@/lib/correction-selection";
import type { TranscriptWord } from "@/types/models";

export interface DragState {
  /** Word index where the gesture started, or null when idle. */
  anchor: number | null;
  /** Word index the pointer last touched, or null when idle. */
  focus: number | null;
  /** True between pointer-down-on-word and pointer-up. */
  dragging: boolean;
}

export const IDLE_DRAG: DragState = { anchor: null, focus: null, dragging: false };

export function beginDrag(index: number): DragState {
  return { anchor: index, focus: index, dragging: true };
}

/** Pointer crossed onto word `index`; no-op when not dragging. */
export function extendDrag(state: DragState, index: number): DragState {
  if (!state.dragging || state.anchor === null) return state;
  if (state.focus === index) return state;
  return { anchor: state.anchor, focus: index, dragging: true };
}

/** Pointer released — the range (if any) survives, the drag flag drops. */
export function endDrag(state: DragState): DragState {
  if (!state.dragging) return state;
  return { anchor: state.anchor, focus: state.focus, dragging: false };
}

/** The selected run, normalized `start <= end`, or null when idle. */
export function dragRange(state: DragState): WordRange | null {
  if (state.anchor === null || state.focus === null) return null;
  return {
    start: Math.min(state.anchor, state.focus),
    end: Math.max(state.anchor, state.focus),
  };
}

/** True once the gesture covered more than the word it started on. */
export function isMultiWord(state: DragState): boolean {
  return (
    state.anchor !== null &&
    state.focus !== null &&
    state.anchor !== state.focus
  );
}

/**
 * The audio span under a word range: first word's start to last word's end.
 * Indices are clamped into the array, so a stale range never throws.
 */
export function rangeTimesMs(
  words: readonly TranscriptWord[],
  range: WordRange
): { startMs: number; endMs: number } {
  const last = words.length - 1;
  const start = Math.min(Math.max(range.start, 0), last);
  const end = Math.min(Math.max(range.end, start), last);
  return { startMs: words[start].s, endMs: words[end].e };
}
