/**
 * transcript.test.ts
 *
 * Unit tests for the pure transcript helpers that drive the highlight loop.
 */

import { describe, it, expect } from "vitest";
import {
  findActiveWordIndex,
  buildLines,
  buildWordLineMap,
  MAX_WORDS_PER_LINE,
  LINE_BREAK_GAP_MS,
} from "./transcript";
import type { TranscriptWord } from "@/types/models";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function word(i: number, s: number, e: number, t = `ك${i}`): TranscriptWord {
  return { i, t, s, e, c: 0.9 };
}

/** Contiguous words: [0,100) [100,200) [200,300) [300,400) */
const contiguous: TranscriptWord[] = [
  word(0, 0, 100),
  word(1, 100, 200),
  word(2, 200, 300),
  word(3, 300, 400),
];

/** Words separated by silence: [500,700) gap [1500,1700) gap [3000,3200) */
const gapped: TranscriptWord[] = [
  word(0, 500, 700),
  word(1, 1500, 1700),
  word(2, 3000, 3200),
];

/** Reference implementation used to cross-check the binary search. */
function linearActiveWordIndex(words: TranscriptWord[], tMs: number): number {
  let found = -1;
  for (let i = 0; i < words.length; i += 1) {
    if (words[i].s <= tMs) found = i;
    else break;
  }
  return found;
}

// ---------------------------------------------------------------------------
// findActiveWordIndex
// ---------------------------------------------------------------------------

describe("findActiveWordIndex", () => {
  it("returns -1 for an empty array at any time", () => {
    expect(findActiveWordIndex([], 0)).toBe(-1);
    expect(findActiveWordIndex([], -1000)).toBe(-1);
    expect(findActiveWordIndex([], 9_999_999)).toBe(-1);
  });

  it("returns -1 before the first word starts", () => {
    expect(findActiveWordIndex(gapped, 0)).toBe(-1);
    expect(findActiveWordIndex(gapped, 499)).toBe(-1);
    expect(findActiveWordIndex(gapped, -1)).toBe(-1);
  });

  it("activates a word exactly on its start boundary", () => {
    expect(findActiveWordIndex(contiguous, 0)).toBe(0);
    expect(findActiveWordIndex(contiguous, 100)).toBe(1);
    expect(findActiveWordIndex(contiguous, 200)).toBe(2);
    expect(findActiveWordIndex(contiguous, 300)).toBe(3);
  });

  it("keeps word i active over the whole half-open range [s[i], s[i+1])", () => {
    expect(findActiveWordIndex(contiguous, 1)).toBe(0);
    expect(findActiveWordIndex(contiguous, 99)).toBe(0);
    expect(findActiveWordIndex(contiguous, 199)).toBe(1);
    expect(findActiveWordIndex(contiguous, 299)).toBe(2);
  });

  it("holds the previous word through a silent gap", () => {
    // 700..1500 is silence; word 0 stays lit rather than flickering off.
    expect(findActiveWordIndex(gapped, 700)).toBe(0);
    expect(findActiveWordIndex(gapped, 1100)).toBe(0);
    expect(findActiveWordIndex(gapped, 1499)).toBe(0);
    expect(findActiveWordIndex(gapped, 1500)).toBe(1);
    expect(findActiveWordIndex(gapped, 2999)).toBe(1);
  });

  it("stays on the last word after the transcript ends", () => {
    expect(findActiveWordIndex(gapped, 3200)).toBe(2);
    expect(findActiveWordIndex(gapped, 60_000)).toBe(2);
    expect(findActiveWordIndex(contiguous, 400)).toBe(3);
  });

  it("handles a single-word transcript", () => {
    const one = [word(0, 250, 900)];
    expect(findActiveWordIndex(one, 249)).toBe(-1);
    expect(findActiveWordIndex(one, 250)).toBe(0);
    expect(findActiveWordIndex(one, 100_000)).toBe(0);
  });

  it("matches a linear scan across a 6000-word transcript and stays fast", () => {
    const big: TranscriptWord[] = [];
    for (let i = 0; i < 6000; i += 1) {
      const s = i * 400;
      big.push(word(i, s, s + 300));
    }

    // Correctness against the reference implementation on sampled times.
    for (let t = -500; t < 6000 * 400 + 1000; t += 977) {
      expect(findActiveWordIndex(big, t)).toBe(linearActiveWordIndex(big, t));
    }

    // Performance sanity: 60fps for 10 minutes is ~36k lookups. Binary search
    // over 6000 words is ~13 comparisons, so this must be comfortably fast.
    const started = performance.now();
    let sink = 0;
    for (let n = 0; n < 50_000; n += 1) {
      sink += findActiveWordIndex(big, (n * 331) % 2_400_000);
    }
    const elapsed = performance.now() - started;
    expect(sink).toBeGreaterThan(0);
    expect(elapsed).toBeLessThan(500);
  });
});

// ---------------------------------------------------------------------------
// buildLines
// ---------------------------------------------------------------------------

describe("buildLines", () => {
  it("returns no lines for an empty transcript", () => {
    expect(buildLines([])).toEqual([]);
  });

  it("keeps a short continuous run on one line", () => {
    const lines = buildLines(contiguous);
    expect(lines).toHaveLength(1);
    expect(lines[0].index).toBe(0);
    expect(lines[0].startIndex).toBe(0);
    expect(lines[0].words).toHaveLength(4);
    expect(lines[0].startMs).toBe(0);
    expect(lines[0].endMs).toBe(400);
  });

  it("breaks after MAX_WORDS_PER_LINE words when there is no pause", () => {
    const dense: TranscriptWord[] = [];
    for (let i = 0; i < MAX_WORDS_PER_LINE * 2 + 3; i += 1) {
      dense.push(word(i, i * 100, i * 100 + 90));
    }
    const lines = buildLines(dense);
    expect(lines).toHaveLength(3);
    expect(lines[0].words).toHaveLength(MAX_WORDS_PER_LINE);
    expect(lines[1].words).toHaveLength(MAX_WORDS_PER_LINE);
    expect(lines[2].words).toHaveLength(3);
    expect(lines[1].startIndex).toBe(MAX_WORDS_PER_LINE);
    expect(lines[2].startIndex).toBe(MAX_WORDS_PER_LINE * 2);
  });

  it("breaks on a pause longer than LINE_BREAK_GAP_MS", () => {
    const paused: TranscriptWord[] = [
      word(0, 0, 200),
      word(1, 300, 500),
      // gap of exactly LINE_BREAK_GAP_MS + 1 -> break
      word(2, 500 + LINE_BREAK_GAP_MS + 1, 500 + LINE_BREAK_GAP_MS + 200),
    ];
    const lines = buildLines(paused);
    expect(lines).toHaveLength(2);
    expect(lines[0].words.map((w) => w.i)).toEqual([0, 1]);
    expect(lines[1].words.map((w) => w.i)).toEqual([2]);
  });

  it("does not break on a pause of exactly LINE_BREAK_GAP_MS", () => {
    const borderline: TranscriptWord[] = [
      word(0, 0, 200),
      word(1, 200 + LINE_BREAK_GAP_MS, 200 + LINE_BREAK_GAP_MS + 100),
    ];
    expect(buildLines(borderline)).toHaveLength(1);
  });

  it("covers every word exactly once, in order", () => {
    const mixed: TranscriptWord[] = [];
    let clock = 0;
    for (let i = 0; i < 200; i += 1) {
      const s = clock;
      const e = s + 180;
      mixed.push(word(i, s, e));
      clock = e + (i % 17 === 0 ? 2500 : 60);
    }
    const lines = buildLines(mixed);
    const flat = lines.flatMap((l) => l.words.map((w) => w.i));
    expect(flat).toEqual(mixed.map((w) => w.i));
    lines.forEach((line, idx) => {
      expect(line.index).toBe(idx);
      expect(line.words.length).toBeLessThanOrEqual(MAX_WORDS_PER_LINE);
      expect(mixed[line.startIndex].i).toBe(line.words[0].i);
      expect(line.startMs).toBe(line.words[0].s);
      expect(line.endMs).toBe(line.words[line.words.length - 1].e);
    });
  });

  it("groups a 6000-word transcript into whole lines", () => {
    const big: TranscriptWord[] = [];
    for (let i = 0; i < 6000; i += 1) {
      const s = i * 400;
      big.push(word(i, s, s + 300));
    }
    const lines = buildLines(big);
    expect(lines).toHaveLength(Math.ceil(6000 / MAX_WORDS_PER_LINE));
    expect(lines.reduce((n, l) => n + l.words.length, 0)).toBe(6000);
  });
});

// ---------------------------------------------------------------------------
// buildWordLineMap
// ---------------------------------------------------------------------------

describe("buildWordLineMap", () => {
  it("maps every word index to the line that contains it", () => {
    const dense: TranscriptWord[] = [];
    for (let i = 0; i < 20; i += 1) dense.push(word(i, i * 100, i * 100 + 90));
    const lines = buildLines(dense);
    const map = buildWordLineMap(lines, dense.length);

    expect(map).toHaveLength(20);
    for (const line of lines) {
      for (const w of line.words) {
        expect(map[w.i]).toBe(line.index);
      }
    }
  });

  it("returns an empty map for an empty transcript", () => {
    expect(buildWordLineMap([], 0)).toHaveLength(0);
  });
});
