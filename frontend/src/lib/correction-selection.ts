/**
 * Word-range selection for the correction UI — pure, no DOM, no React.
 *
 * The transcript is a flat array of words; a correction is filed against a
 * contiguous run of them. Selection is two clicks: the first anchors the run,
 * the second closes it, and any further click starts over on the word just
 * clicked. Escape (the caller's key handler) resets to the empty state.
 *
 * The chunk bridge lives here too: POST /api/corrections/ is keyed by
 * `chunk_id`, but the transcript payload only carries word indices, so the UI
 * resolves the owning chunk from GET /api/segments/{id}/chunks/.
 */

import type { SegmentChunk, TranscriptWord } from "@/types/models";

// ---------------------------------------------------------------------------
// Selection state
// ---------------------------------------------------------------------------

export interface SelectionState {
  /** Word index of the first click, or null when nothing is selected. */
  anchor: number | null;
  /** Word index of the second click, or null while only the anchor is set. */
  focus: number | null;
}

/** A closed, normalized run of word indices: `start <= end`. */
export interface WordRange {
  start: number;
  end: number;
}

export const EMPTY_SELECTION: SelectionState = { anchor: null, focus: null };

/**
 * Apply a click on word `index`.
 *
 * empty -> anchor set · anchor set -> range closed · range closed -> re-anchor.
 */
export function selectWord(
  state: SelectionState,
  index: number
): SelectionState {
  if (state.anchor === null) return { anchor: index, focus: null };
  if (state.focus === null) return { anchor: state.anchor, focus: index };
  return { anchor: index, focus: null };
}

/** The Escape / dismiss transition. */
export function clearSelection(): SelectionState {
  return EMPTY_SELECTION;
}

/**
 * The selected run, normalized so `start <= end` however it was dragged.
 *
 * A lone anchor is a legitimate one-word range — correcting a single word is
 * the common case and should not need a second click on the same word.
 */
export function selectedRange(state: SelectionState): WordRange | null {
  if (state.anchor === null) return null;
  const other = state.focus ?? state.anchor;
  return {
    start: Math.min(state.anchor, other),
    end: Math.max(state.anchor, other),
  };
}

/** True once both ends have been clicked. */
export function isRangeComplete(state: SelectionState): boolean {
  return state.anchor !== null && state.focus !== null;
}

/** Whether word `index` falls inside the selected run (drives the underline). */
export function isWordSelected(state: SelectionState, index: number): boolean {
  const range = selectedRange(state);
  return range !== null && index >= range.start && index <= range.end;
}

/** The original transcript text under a range, as one space-joined string. */
export function rangeText(words: TranscriptWord[], range: WordRange): string {
  return words
    .filter((word) => word.i >= range.start && word.i <= range.end)
    .map((word) => word.t)
    .join(" ");
}

// ---------------------------------------------------------------------------
// Chunk bridge
// ---------------------------------------------------------------------------

/**
 * The chunk a word belongs to.
 *
 * Prefers the chunk whose `[word_start, word_end]` contains `wordIndex`; when
 * the chunk map has a hole (a word inside a gap between chunks) it falls back
 * to the nearest chunk by index distance. Returns null only for an empty list.
 */
export function pickChunkForWord(
  chunks: SegmentChunk[],
  wordIndex: number
): SegmentChunk | null {
  let nearest: SegmentChunk | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;

  for (const chunk of chunks) {
    if (wordIndex >= chunk.word_start && wordIndex <= chunk.word_end) {
      return chunk;
    }
    const distance =
      wordIndex < chunk.word_start
        ? chunk.word_start - wordIndex
        : wordIndex - chunk.word_end;
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearest = chunk;
    }
  }

  return nearest;
}
