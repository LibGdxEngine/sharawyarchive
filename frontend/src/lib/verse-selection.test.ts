import { describe, expect, it } from "vitest";
import {
  IDLE_DRAG,
  beginDrag,
  dragRange,
  endDrag,
  extendDrag,
  isMultiWord,
  rangeTimesMs,
} from "./verse-selection";
import type { TranscriptWord } from "@/types/models";

const WORDS: TranscriptWord[] = Array.from({ length: 10 }, (_, i) => ({
  i,
  t: `w${i}`,
  s: i * 1000,
  e: i * 1000 + 800,
  c: 0.9,
}));

describe("drag state machine", () => {
  it("walks begin → extend → end and keeps the range", () => {
    let state = beginDrag(3);
    expect(state.dragging).toBe(true);
    state = extendDrag(state, 6);
    state = endDrag(state);
    expect(state.dragging).toBe(false);
    expect(dragRange(state)).toEqual({ start: 3, end: 6 });
  });

  it("normalizes a backwards sweep", () => {
    const state = extendDrag(beginDrag(7), 2);
    expect(dragRange(state)).toEqual({ start: 2, end: 7 });
  });

  it("ignores extend when idle", () => {
    expect(extendDrag(IDLE_DRAG, 4)).toBe(IDLE_DRAG);
    expect(dragRange(IDLE_DRAG)).toBeNull();
  });

  it("tells a click apart from a sweep", () => {
    expect(isMultiWord(beginDrag(3))).toBe(false);
    expect(isMultiWord(extendDrag(beginDrag(3), 4))).toBe(true);
  });
});

describe("rangeTimesMs", () => {
  it("spans first word start to last word end", () => {
    expect(rangeTimesMs(WORDS, { start: 2, end: 5 })).toEqual({
      startMs: 2000,
      endMs: 5800,
    });
  });

  it("clamps out-of-bounds indices instead of throwing", () => {
    expect(rangeTimesMs(WORDS, { start: -3, end: 99 })).toEqual({
      startMs: 0,
      endMs: 9800,
    });
  });
});
