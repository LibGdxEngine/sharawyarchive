/**
 * clip-range.test.ts
 *
 * Unit tests for the pure clip range constraints. The API rejects spans
 * outside 15–60s, so these functions must never let a drag produce one.
 */

import { describe, it, expect } from "vitest";
import {
  MIN_CLIP_MS,
  MAX_CLIP_MS,
  DEFAULT_CLIP_MS,
  canClipSegment,
  clampClipRange,
  defaultClipRange,
  moveClipEnd,
  moveClipStart,
} from "./clip-range";

/** A 10-minute segment — long enough that neither bound is the segment edge. */
const LONG = 600_000;

describe("clampClipRange", () => {
  it("clamps both ends into the segment", () => {
    expect(clampClipRange({ startMs: -5_000, endMs: 25_000 }, LONG)).toEqual({
      startMs: 0,
      endMs: 25_000,
    });
    expect(
      clampClipRange({ startMs: 570_000, endMs: 900_000 }, LONG)
    ).toEqual({ startMs: 570_000, endMs: LONG });
  });

  it("swaps inverted ends", () => {
    expect(clampClipRange({ startMs: 90_000, endMs: 60_000 }, LONG)).toEqual({
      startMs: 60_000,
      endMs: 90_000,
    });
  });

  it("grows a too-short span forward to the 15s minimum", () => {
    expect(clampClipRange({ startMs: 10_000, endMs: 12_000 }, LONG)).toEqual({
      startMs: 10_000,
      endMs: 10_000 + MIN_CLIP_MS,
    });
  });

  it("pulls the start back when growing would pass the end of the segment", () => {
    expect(
      clampClipRange({ startMs: LONG - 3_000, endMs: LONG }, LONG)
    ).toEqual({ startMs: LONG - MIN_CLIP_MS, endMs: LONG });
  });

  it("cuts a too-long span back to the 60s maximum", () => {
    expect(clampClipRange({ startMs: 30_000, endMs: 200_000 }, LONG)).toEqual({
      startMs: 30_000,
      endMs: 30_000 + MAX_CLIP_MS,
    });
  });

  it("collapses to the whole segment when it is shorter than the minimum", () => {
    expect(clampClipRange({ startMs: 2_000, endMs: 5_000 }, 9_000)).toEqual({
      startMs: 0,
      endMs: 9_000,
    });
    expect(canClipSegment(9_000)).toBe(false);
    expect(canClipSegment(MIN_CLIP_MS)).toBe(true);
  });
});

describe("moveClipStart", () => {
  const range = { startMs: 100_000, endMs: 130_000 };

  it("moves the start and holds the end still", () => {
    expect(moveClipStart(range, 90_000, LONG)).toEqual({
      startMs: 90_000,
      endMs: 130_000,
    });
  });

  it("stops at end - 15s when dragged across the end handle", () => {
    expect(moveClipStart(range, 400_000, LONG)).toEqual({
      startMs: 130_000 - MIN_CLIP_MS,
      endMs: 130_000,
    });
  });

  it("stops at end - 60s when dragged far back", () => {
    expect(moveClipStart(range, 0, LONG)).toEqual({
      startMs: 130_000 - MAX_CLIP_MS,
      endMs: 130_000,
    });
  });

  it("never goes below zero near the head of the segment", () => {
    expect(moveClipStart({ startMs: 5_000, endMs: 25_000 }, -9_000, LONG)).toEqual(
      { startMs: 0, endMs: 25_000 }
    );
  });
});

describe("moveClipEnd", () => {
  const range = { startMs: 100_000, endMs: 130_000 };

  it("moves the end and holds the start still", () => {
    expect(moveClipEnd(range, 150_000, LONG)).toEqual({
      startMs: 100_000,
      endMs: 150_000,
    });
  });

  it("stops at start + 15s when dragged across the start handle", () => {
    expect(moveClipEnd(range, 20_000, LONG)).toEqual({
      startMs: 100_000,
      endMs: 100_000 + MIN_CLIP_MS,
    });
  });

  it("stops at start + 60s when dragged far forward", () => {
    expect(moveClipEnd(range, 500_000, LONG)).toEqual({
      startMs: 100_000,
      endMs: 100_000 + MAX_CLIP_MS,
    });
  });

  it("never passes the end of the segment", () => {
    expect(
      moveClipEnd({ startMs: LONG - 20_000, endMs: LONG - 5_000 }, LONG + 60_000, LONG)
    ).toEqual({ startMs: LONG - 20_000, endMs: LONG });
  });
});

describe("defaultClipRange", () => {
  it("starts at the playhead with the default span", () => {
    expect(defaultClipRange(42_000, LONG)).toEqual({
      startMs: 42_000,
      endMs: 42_000 + DEFAULT_CLIP_MS,
    });
  });

  it("backs off the tail so the clip still fits", () => {
    expect(defaultClipRange(LONG - 4_000, LONG)).toEqual({
      startMs: LONG - MIN_CLIP_MS,
      endMs: LONG,
    });
  });

  it("ignores a playhead outside the segment", () => {
    expect(defaultClipRange(-1_000, LONG)).toEqual({
      startMs: 0,
      endMs: DEFAULT_CLIP_MS,
    });
  });
});
