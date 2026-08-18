/**
 * Pure transcript helpers — no DOM, no React, no store.
 *
 * These functions run inside a requestAnimationFrame loop (up to 60×/second on
 * arrays of several thousand words), so they must stay allocation-free and
 * logarithmic. Everything here is a pure function of its arguments and is unit
 * tested in transcript.test.ts.
 *
 * All timestamps are integer milliseconds (see CLAUDE.md rule 5).
 */

import type { TranscriptWord } from "@/types/models";

// ---------------------------------------------------------------------------
// Active word lookup
// ---------------------------------------------------------------------------

/**
 * Index of the word being spoken at `tMs`, via binary search.
 *
 * `words` must be sorted ascending by `s`. The active word is the LAST word
 * whose `s` is <= `tMs`, i.e. word `i` stays active for `s[i] <= t < s[i+1]`
 * — inter-word silence keeps the previous word lit rather than flickering off.
 *
 * Returns -1 when the array is empty or `tMs` precedes the first word.
 */
export function findActiveWordIndex(
  words: TranscriptWord[],
  tMs: number
): number {
  let lo = 0;
  let hi = words.length - 1;
  let found = -1;

  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].s <= tMs) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  return found;
}

// ---------------------------------------------------------------------------
// Line grouping
// ---------------------------------------------------------------------------

/** Words per line before a forced break. */
export const MAX_WORDS_PER_LINE = 9;

/** Silence between two words that forces a line break, in milliseconds. */
export const LINE_BREAK_GAP_MS = 1200;

export interface TranscriptLine {
  /** Position of this line within the returned array. */
  index: number;
  /** Index into the source `words` array of this line's first word. */
  startIndex: number;
  words: TranscriptWord[];
  startMs: number;
  endMs: number;
}

/**
 * Group a flat word array into display lines for virtualization.
 *
 * A line closes when it reaches MAX_WORDS_PER_LINE words, or when the silence
 * before the next word exceeds LINE_BREAK_GAP_MS — so lines fall on the
 * Sheikh's natural pauses instead of an arbitrary grid.
 */
export function buildLines(words: TranscriptWord[]): TranscriptLine[] {
  const lines: TranscriptLine[] = [];
  let bucket: TranscriptWord[] = [];
  let startIndex = 0;

  const flush = (): void => {
    if (bucket.length === 0) return;
    lines.push({
      index: lines.length,
      startIndex,
      words: bucket,
      startMs: bucket[0].s,
      endMs: bucket[bucket.length - 1].e,
    });
    bucket = [];
  };

  for (let i = 0; i < words.length; i += 1) {
    const word = words[i];
    if (bucket.length > 0) {
      const prev = bucket[bucket.length - 1];
      if (
        bucket.length >= MAX_WORDS_PER_LINE ||
        word.s - prev.e > LINE_BREAK_GAP_MS
      ) {
        flush();
      }
    }
    if (bucket.length === 0) startIndex = i;
    bucket.push(word);
  }
  flush();

  return lines;
}

/**
 * Reverse index: word position -> line position. Built once per transcript so
 * the highlight loop can resolve the active line in O(1).
 */
export function buildWordLineMap(
  lines: TranscriptLine[],
  wordCount: number
): Int32Array {
  const map = new Int32Array(wordCount);
  for (const line of lines) {
    for (let k = 0; k < line.words.length; k += 1) {
      map[line.startIndex + k] = line.index;
    }
  }
  return map;
}
