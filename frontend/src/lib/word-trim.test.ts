import { describe, expect, it } from "vitest";
import { MIN_CLIP_MS } from "./clip-range";
import {
  isTrimLegal,
  moveTrimEnd,
  moveTrimStart,
  nearestWordIndex,
  trimFromRange,
  trimFromTimes,
  trimTimesMs,
} from "./word-trim";
import type { TranscriptWord } from "@/types/models";

/** 120 words on a 1 s grid: word k spans [k*1000, k*1000+800]. */
const WORDS: TranscriptWord[] = Array.from({ length: 120 }, (_, i) => ({
  i,
  t: `w${i}`,
  s: i * 1000,
  e: i * 1000 + 800,
  c: 0.9,
}));

describe("trimFromRange", () => {
  it("keeps a legal selection as-is", () => {
    // words 10..30 → 20.8 s.
    const trim = trimFromRange(WORDS, { start: 10, end: 30 });
    expect(trim).toEqual({ startWord: 10, endWord: 30 });
    expect(isTrimLegal(WORDS, trim)).toBe(true);
  });

  it("grows a short selection outward on both sides", () => {
    const trim = trimFromRange(WORDS, { start: 50, end: 50 });
    expect(trim.startWord).toBeLessThanOrEqual(50);
    expect(trim.endWord).toBeGreaterThanOrEqual(50);
    const { startMs, endMs } = trimTimesMs(WORDS, trim);
    expect(endMs - startMs).toBeGreaterThanOrEqual(MIN_CLIP_MS);
  });

  it("grows forward only at the start of the transcript", () => {
    const trim = trimFromRange(WORDS, { start: 0, end: 0 });
    expect(trim.startWord).toBe(0);
    expect(isTrimLegal(WORDS, trim)).toBe(true);
  });

  it("grows backward only at the tail of the transcript", () => {
    const trim = trimFromRange(WORDS, { start: 119, end: 119 });
    expect(trim.endWord).toBe(119);
    expect(isTrimLegal(WORDS, trim)).toBe(true);
  });

  it("keeps an over-long selection — there is no maximum", () => {
    const trim = trimFromRange(WORDS, { start: 0, end: 119 });
    expect(trim).toEqual({ startWord: 0, endWord: 119 });
    expect(isTrimLegal(WORDS, trim)).toBe(true);
  });

  it("reports an impossible span honestly", () => {
    // One word → 0.8 s, below the one-second floor.
    const tiny = WORDS.slice(0, 1);
    const trim = trimFromRange(tiny, { start: 0, end: 0 });
    expect(trim).toEqual({ startWord: 0, endWord: 0 });
    expect(isTrimLegal(tiny, trim)).toBe(false);
  });
});

describe("moveTrimStart / moveTrimEnd", () => {
  const base = trimFromRange(WORDS, { start: 40, end: 60 }); // 20.8 s

  it("moves by whole words and clamps against the minimum", () => {
    // Dragging the start almost onto the end must park at MIN_CLIP_MS.
    const trim = moveTrimStart(WORDS, base, 60);
    const { startMs, endMs } = trimTimesMs(WORDS, trim);
    expect(endMs - startMs).toBeGreaterThanOrEqual(MIN_CLIP_MS);
    expect(trim.endWord).toBe(60);
  });

  it("lets the start sweep all the way back — no maximum", () => {
    const trim = moveTrimStart(WORDS, base, 0);
    expect(trim.startWord).toBe(0);
    expect(trim.endWord).toBe(60);
  });

  it("clamps the end against the minimum, then the transcript edge", () => {
    const tooFar = moveTrimEnd(WORDS, base, 119);
    expect(tooFar).toEqual({ startWord: 40, endWord: 119 });

    const tooNear = moveTrimEnd(WORDS, base, 40);
    const near = trimTimesMs(WORDS, tooNear);
    expect(near.endMs - near.startMs).toBeGreaterThanOrEqual(MIN_CLIP_MS);
  });

  it("never inverts the handles", () => {
    expect(moveTrimStart(WORDS, base, 119).startWord).toBeLessThanOrEqual(
      base.endWord
    );
    expect(moveTrimEnd(WORDS, base, 0).endWord).toBeGreaterThanOrEqual(
      base.startWord
    );
  });
});

describe("nearestWordIndex", () => {
  it("finds the word being spoken", () => {
    // word 7 spans [7000, 7800].
    expect(nearestWordIndex(WORDS, 7_000)).toBe(7);
    expect(nearestWordIndex(WORDS, 7_400)).toBe(7);
    expect(nearestWordIndex(WORDS, 7_800)).toBe(7);
  });

  it("takes the nearer edge inside a pause", () => {
    // The gap after word 7 runs [7800, 8000]; its midpoint is 7900.
    expect(nearestWordIndex(WORDS, 7_850)).toBe(7);
    expect(nearestWordIndex(WORDS, 7_950)).toBe(8);
  });

  it("clamps outside the transcript rather than returning -1", () => {
    expect(nearestWordIndex(WORDS, -5_000)).toBe(0);
    expect(nearestWordIndex(WORDS, 10_000_000)).toBe(WORDS.length - 1);
  });

  it("reports -1 only for an empty transcript", () => {
    expect(nearestWordIndex([], 1_000)).toBe(-1);
  });
});

describe("trimFromTimes", () => {
  it("snaps a typed range outward to whole words", () => {
    // 7400 is mid-word-7, 20400 mid-word-20.
    expect(trimFromTimes(WORDS, { startMs: 7_400, endMs: 20_400 })).toEqual({
      startWord: 7,
      endWord: 20,
    });
  });

  it("grows a range too short to be legal", () => {
    const trim = trimFromTimes(WORDS, { startMs: 50_100, endMs: 50_200 });
    expect(isTrimLegal(WORDS, trim)).toBe(true);
  });

  it("tolerates an inverted range", () => {
    expect(trimFromTimes(WORDS, { startMs: 40_000, endMs: 10_000 })).toEqual(
      trimFromTimes(WORDS, { startMs: 10_000, endMs: 40_000 })
    );
  });

  it("clamps a range that runs past the transcript", () => {
    const trim = trimFromTimes(WORDS, { startMs: 0, endMs: 10_000_000 });
    expect(trim).toEqual({ startWord: 0, endWord: WORDS.length - 1 });
  });
});
