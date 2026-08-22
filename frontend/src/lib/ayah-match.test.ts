import { describe, expect, it } from "vitest";
import { normalizeForIndex } from "./arabic";
import {
  MATCH_THRESHOLD,
  MIN_MATCHED_TOKENS,
  PER_WORD_HIGHLIGHT_DENSITY,
  activeQuranToken,
  alignmentDensity,
  buildVerseBlocks,
  matchAyahsInTranscript,
} from "./ayah-match";
import type { AyahRef } from "./ayah-match";
import type { TranscriptWord } from "@/types/models";

/** Synthetic transcript: 500 ms grid, i === array position (like the API). */
function words(...texts: string[]): TranscriptWord[] {
  return texts.map((t, i) => ({ i, t, s: i * 500, e: i * 500 + 400, c: 0.9 }));
}

// Uthmani-style text (diacritics, madda) — ASR words below are bare.
const AYAH_28: AyahRef = {
  number: 28,
  textUthmani: "لِمَن شَآءَ مِنكُمْ أَن يَسْتَقِيمَ",
};
const AYAH_29: AyahRef = {
  number: 29,
  textUthmani: "وَمَا تَشَآءُونَ إِلَّآ أَن يَشَآءَ ٱللَّهُ رَبُّ ٱلْعَٰلَمِينَ",
};

const TAFSEER = ["يقول", "الشيخ", "رحمه", "الله", "في", "هذه", "الاية"];
const RECITED_28 = ["لمن", "شاء", "منكم", "أن", "يستقيم"];

function match(ayahs: AyahRef[], transcript: TranscriptWord[]) {
  return matchAyahsInTranscript(ayahs, transcript, normalizeForIndex);
}

describe("matchAyahsInTranscript", () => {
  it("anchors an exact recitation and maps every word to its token", () => {
    const transcript = words(...TAFSEER, ...RECITED_28, ...TAFSEER);
    const [found, ...rest] = match([AYAH_28], transcript);

    expect(rest).toEqual([]);
    expect(found.ayahNumber).toBe(28);
    expect(found.wordStart).toBe(TAFSEER.length);
    expect(found.wordEnd).toBe(TAFSEER.length + RECITED_28.length - 1);
    expect(found.matched).toBe(5);
    expect(found.score).toBe(1);
    expect([...found.tokenMap]).toEqual([0, 1, 2, 3, 4]);
  });

  it("accepts a noisy recitation above the threshold, with -1 for the miss", () => {
    // "منكم" mis-heard: 4/5 = 0.8 >= MATCH_THRESHOLD.
    const noisy = ["لمن", "شاء", "منهم", "أن", "يستقيم"];
    const transcript = words(...TAFSEER, ...noisy, ...TAFSEER);
    const [found] = match([AYAH_28], transcript);

    expect(found).toBeDefined();
    expect(found.matched).toBe(4);
    expect([...found.tokenMap]).toEqual([0, 1, -1, 3, 4]);
  });

  it("rejects below the threshold", () => {
    // Only 2/5 tokens present — under both gates.
    const transcript = words(...TAFSEER, "لمن", "شاء", ...TAFSEER);
    expect(match([AYAH_28], transcript)).toEqual([]);
    expect(2 / 5).toBeLessThan(MATCH_THRESHOLD);
  });

  it("never anchors an ayah shorter than MIN_MATCHED_TOKENS", () => {
    const short: AyahRef = { number: 1, textUthmani: "الٓمٓ" };
    const transcript = words("الم", "ذلك", "الكتاب");
    expect(match([short], transcript)).toEqual([]);
    expect(1).toBeLessThan(MIN_MATCHED_TOKENS);
  });

  it("finds a repeated recitation as two separate anchors", () => {
    const transcript = words(
      ...RECITED_28,
      ...TAFSEER,
      ...RECITED_28,
      ...TAFSEER
    );
    const found = match([AYAH_28], transcript);

    expect(found).toHaveLength(2);
    expect(found[0].wordStart).toBe(0);
    expect(found[1].wordStart).toBe(RECITED_28.length + TAFSEER.length);
  });

  it("orders a multi-ayah run by position", () => {
    const recited29 = [
      "وما",
      "تشاءون",
      "إلا",
      "أن",
      "يشاء",
      "الله",
      "رب",
      "العالمين",
    ];
    const transcript = words(...RECITED_28, ...TAFSEER, ...recited29);
    const found = match([AYAH_29, AYAH_28], transcript);

    expect(found.map((m) => m.ayahNumber)).toEqual([28, 29]);
  });

  it("resolves overlapping candidates greedily by matched count", () => {
    // 29 contains "أن يشاء" — with 28 also present, the shared words must
    // belong to exactly one kept span.
    const recited29 = [
      "وما",
      "تشاءون",
      "إلا",
      "أن",
      "يشاء",
      "الله",
      "رب",
      "العالمين",
    ];
    const transcript = words(...recited29);
    const found = match([AYAH_28, AYAH_29], transcript);

    expect(found).toHaveLength(1);
    expect(found[0].ayahNumber).toBe(29);
  });

  it("ignores words that normalize to nothing", () => {
    const transcript = words("ـــ", ...RECITED_28, "ًٌٍ");
    const [found] = match([AYAH_28], transcript);
    expect(found.wordStart).toBe(1);
    expect(found.wordEnd).toBe(RECITED_28.length);
  });
});

describe("buildVerseBlocks", () => {
  it("interleaves tafseer runs around the anchored cards", () => {
    const transcript = words(...TAFSEER, ...RECITED_28, ...TAFSEER);
    const matches = match([AYAH_28], transcript);
    const blocks = buildVerseBlocks(transcript, [AYAH_28], matches, 28);

    expect(blocks).toHaveLength(3);
    expect(blocks[0]).toMatchObject({ kind: "tafseer", wordStart: 0, wordEnd: 6 });
    expect(blocks[1]).toMatchObject({ kind: "ayah", ayah: AYAH_28 });
    expect(blocks[2]).toMatchObject({
      kind: "tafseer",
      wordStart: TAFSEER.length + RECITED_28.length,
      wordEnd: transcript.length - 1,
    });
  });

  it("pins the focused ayah at top when it found no anchor", () => {
    const transcript = words(...TAFSEER);
    const blocks = buildVerseBlocks(transcript, [AYAH_28], [], 28);

    expect(blocks[0]).toEqual({ kind: "ayah", ayah: AYAH_28, match: null });
    expect(blocks[1]).toMatchObject({ kind: "tafseer", wordStart: 0 });
  });

  it("does not pin when the focused ayah is anchored inline", () => {
    const transcript = words(...RECITED_28);
    const matches = match([AYAH_28], transcript);
    const blocks = buildVerseBlocks(transcript, [AYAH_28], matches, 28);

    expect(blocks).toHaveLength(1);
    expect(blocks[0].kind).toBe("ayah");
  });
});

describe("activeQuranToken / alignmentDensity", () => {
  it("maps the active word and keeps the previous token through gaps", () => {
    const noisy = ["لمن", "شاء", "منهم", "أن", "يستقيم"];
    const transcript = words(...noisy);
    const [found] = match([AYAH_28], transcript);

    expect(activeQuranToken(found, 0)).toBe(0);
    // The mis-heard word keeps the previous token lit.
    expect(activeQuranToken(found, 2)).toBe(1);
    expect(activeQuranToken(found, 4)).toBe(4);
    expect(activeQuranToken(found, 99)).toBe(-1);
  });

  it("reports density for the per-word/whole-card decision", () => {
    const transcript = words(...RECITED_28);
    const [found] = match([AYAH_28], transcript);
    expect(alignmentDensity(found)).toBe(1);
    expect(alignmentDensity(found)).toBeGreaterThanOrEqual(
      PER_WORD_HIGHLIGHT_DENSITY
    );
  });
});
