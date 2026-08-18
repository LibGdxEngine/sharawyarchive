/**
 * correction-selection.test.ts
 *
 * Unit tests for the pure word-range selection reducer and the chunk bridge.
 */

import { describe, it, expect } from "vitest";
import {
  EMPTY_SELECTION,
  clearSelection,
  isRangeComplete,
  isWordSelected,
  pickChunkForWord,
  rangeText,
  selectWord,
  selectedRange,
} from "./correction-selection";
import type { SegmentChunk, TranscriptWord } from "@/types/models";

function word(i: number, t: string): TranscriptWord {
  return { i, t, s: i * 100, e: i * 100 + 90, c: 0.9 };
}

const words: TranscriptWord[] = [
  word(0, "بسم"),
  word(1, "الله"),
  word(2, "الرحمن"),
  word(3, "الرحيم"),
];

function chunk(
  chunk_id: number,
  word_start: number,
  word_end: number
): SegmentChunk {
  return {
    chunk_id,
    word_start,
    word_end,
    start_ms: word_start * 100,
    end_ms: word_end * 100 + 90,
  };
}

// ---------------------------------------------------------------------------
// selectWord / selectedRange
// ---------------------------------------------------------------------------

describe("selectWord", () => {
  it("anchors on the first click and offers a one-word range", () => {
    const state = selectWord(EMPTY_SELECTION, 2);
    expect(state).toEqual({ anchor: 2, focus: null });
    expect(isRangeComplete(state)).toBe(false);
    expect(selectedRange(state)).toEqual({ start: 2, end: 2 });
  });

  it("closes the range on the second click", () => {
    const state = selectWord(selectWord(EMPTY_SELECTION, 1), 3);
    expect(state).toEqual({ anchor: 1, focus: 3 });
    expect(isRangeComplete(state)).toBe(true);
    expect(selectedRange(state)).toEqual({ start: 1, end: 3 });
  });

  it("normalizes a range closed backwards", () => {
    const state = selectWord(selectWord(EMPTY_SELECTION, 3), 0);
    expect(state).toEqual({ anchor: 3, focus: 0 });
    expect(selectedRange(state)).toEqual({ start: 0, end: 3 });
  });

  it("re-anchors on the third click instead of extending", () => {
    const closed = selectWord(selectWord(EMPTY_SELECTION, 0), 2);
    const reanchored = selectWord(closed, 3);
    expect(reanchored).toEqual({ anchor: 3, focus: null });
    expect(selectedRange(reanchored)).toEqual({ start: 3, end: 3 });
  });

  it("supports a range that starts and ends on the same word", () => {
    const state = selectWord(selectWord(EMPTY_SELECTION, 2), 2);
    expect(selectedRange(state)).toEqual({ start: 2, end: 2 });
    expect(isRangeComplete(state)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// clearSelection (Escape)
// ---------------------------------------------------------------------------

describe("clearSelection", () => {
  it("resets any state back to empty", () => {
    const closed = selectWord(selectWord(EMPTY_SELECTION, 1), 3);
    expect(clearSelection()).toEqual(EMPTY_SELECTION);
    expect(selectedRange(clearSelection())).toBeNull();
    expect(isRangeComplete(closed)).toBe(true);
    expect(isRangeComplete(clearSelection())).toBe(false);
  });

  it("has no range while empty", () => {
    expect(selectedRange(EMPTY_SELECTION)).toBeNull();
    expect(isWordSelected(EMPTY_SELECTION, 0)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isWordSelected
// ---------------------------------------------------------------------------

describe("isWordSelected", () => {
  it("covers the closed range and nothing outside it", () => {
    const state = selectWord(selectWord(EMPTY_SELECTION, 1), 2);
    expect(isWordSelected(state, 0)).toBe(false);
    expect(isWordSelected(state, 1)).toBe(true);
    expect(isWordSelected(state, 2)).toBe(true);
    expect(isWordSelected(state, 3)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// rangeText
// ---------------------------------------------------------------------------

describe("rangeText", () => {
  it("joins the selected words with single spaces", () => {
    expect(rangeText(words, { start: 1, end: 3 })).toBe("الله الرحمن الرحيم");
    expect(rangeText(words, { start: 0, end: 0 })).toBe("بسم");
  });

  it("returns an empty string when the range falls outside the transcript", () => {
    expect(rangeText(words, { start: 40, end: 42 })).toBe("");
  });
});

// ---------------------------------------------------------------------------
// pickChunkForWord — the chunk-id bridge
// ---------------------------------------------------------------------------

describe("pickChunkForWord", () => {
  const chunks = [chunk(9, 0, 10), chunk(10, 11, 20), chunk(11, 30, 40)];

  it("returns the chunk containing the word, boundaries included", () => {
    expect(pickChunkForWord(chunks, 0)?.chunk_id).toBe(9);
    expect(pickChunkForWord(chunks, 10)?.chunk_id).toBe(9);
    expect(pickChunkForWord(chunks, 11)?.chunk_id).toBe(10);
    expect(pickChunkForWord(chunks, 20)?.chunk_id).toBe(10);
    expect(pickChunkForWord(chunks, 35)?.chunk_id).toBe(11);
  });

  it("falls back to the nearest chunk when the word sits in a gap", () => {
    // 22 is 2 past chunk 10 and 8 before chunk 11.
    expect(pickChunkForWord(chunks, 22)?.chunk_id).toBe(10);
    // 29 is 9 past chunk 10 and 1 before chunk 11.
    expect(pickChunkForWord(chunks, 29)?.chunk_id).toBe(11);
    // Past the last chunk entirely.
    expect(pickChunkForWord(chunks, 500)?.chunk_id).toBe(11);
  });

  it("returns null when the segment reports no chunks", () => {
    expect(pickChunkForWord([], 3)).toBeNull();
  });
});
