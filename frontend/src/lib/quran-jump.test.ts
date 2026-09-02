import { describe, expect, it } from "vitest";
import { jumpHref, parseJump, type SurahRef } from "./quran-jump";

const SURAHS: SurahRef[] = [
  { number: 1, name_ar_plain: "الفاتحه", ayah_count: 7 },
  { number: 2, name_ar_plain: "البقره", ayah_count: 286 },
  { number: 30, name_ar_plain: "الروم", ayah_count: 60 },
  { number: 36, name_ar_plain: "يس", ayah_count: 83 },
  { number: 38, name_ar_plain: "ص", ayah_count: 88 },
  { number: 78, name_ar_plain: "النبا", ayah_count: 40 },
];

describe("parseJump — ayah references", () => {
  const pairs = [
    { note: "ascii colon form", input: "2:255" },
    { note: "arabic-indic digits", input: "٢:٢٥٥" },
    { note: "spaces around the colon", input: "2 : 255" },
    { note: "mixed digit systems", input: "٢:255" },
  ];

  it.each(pairs)("$note", ({ input }) => {
    expect(parseJump(input, SURAHS)).toEqual({
      kind: "ayah",
      surah: 2,
      ayah: 255,
    });
  });

  it("reads a surah name followed by an ayah number", () => {
    expect(parseJump("البقرة 255", SURAHS)).toEqual({
      kind: "ayah",
      surah: 2,
      ayah: 255,
    });
  });

  it("tolerates the سورة / آية filler words", () => {
    expect(parseJump("سورة البقرة آية ٢٥٥", SURAHS)).toEqual({
      kind: "ayah",
      surah: 2,
      ayah: 255,
    });
  });

  it("rejects an ayah past the end of the surah", () => {
    // Al-Fatihah has 7 verses, so 8 names nothing.
    expect(parseJump("1:8", SURAHS)).toBeNull();
  });

  it("rejects a surah that does not exist", () => {
    expect(parseJump("115:1", SURAHS)).toBeNull();
  });
});

describe("parseJump — surah references", () => {
  it("matches a name whatever the hamza and ta-marbuta spelling", () => {
    for (const spelling of ["الفاتحة", "الفاتحه", "الفَاتِحَة"]) {
      expect(parseJump(spelling, SURAHS)).toEqual({ kind: "surah", surah: 1 });
    }
  });

  it("matches a name with the definite article dropped", () => {
    expect(parseJump("بقرة", SURAHS)).toEqual({ kind: "surah", surah: 2 });
  });

  it("reads a bare number as a surah, not a juz", () => {
    expect(parseJump("30", SURAHS)).toEqual({ kind: "surah", surah: 30 });
    expect(parseJump("٣٠", SURAHS)).toEqual({ kind: "surah", surah: 30 });
  });

  it("rejects a bare number with no such surah", () => {
    expect(parseJump("115", SURAHS)).toBeNull();
  });
});

describe("parseJump — page and juz references", () => {
  it.each([
    { note: "صفحة spelled out", input: "صفحة ٦٠٤" },
    { note: "ta-marbuta folded", input: "صفحه 604" },
    { note: "with the article", input: "الصفحة 604" },
    { note: "english", input: "page 604" },
  ])("$note", ({ input }) => {
    expect(parseJump(input, SURAHS)).toEqual({ kind: "page", page: 604 });
  });

  it.each([
    { note: "جزء", input: "جزء ٣٠" },
    { note: "with the article", input: "الجزء 30" },
    { note: "short form", input: "جز 30" },
    { note: "english", input: "juz 30" },
  ])("$note", ({ input }) => {
    expect(parseJump(input, SURAHS)).toEqual({ kind: "juz", juz: 30 });
  });

  it("does not read a bare ص as a page — it is surah 38", () => {
    // "ص 38" must never be a coin toss between page 38 and Saad, ayah 38.
    expect(parseJump("ص 38", SURAHS)).toEqual({
      kind: "ayah",
      surah: 38,
      ayah: 38,
    });
    expect(parseJump("ص", SURAHS)).toEqual({ kind: "surah", surah: 38 });
  });

  it("rejects a page or juz past the mushaf", () => {
    expect(parseJump("صفحة 605", SURAHS)).toBeNull();
    expect(parseJump("جزء 31", SURAHS)).toBeNull();
    expect(parseJump("جزء 0", SURAHS)).toBeNull();
  });
});

describe("parseJump — non-references", () => {
  it.each([
    { note: "empty", input: "" },
    { note: "whitespace only", input: "   " },
    { note: "a partial name", input: "الف" },
    { note: "free text", input: "الصبر عند الصدمة" },
  ])("$note yields null", ({ input }) => {
    expect(parseJump(input, SURAHS)).toBeNull();
  });
});

describe("jumpHref", () => {
  it("points an ayah target at the surah page anchored on that verse", () => {
    expect(jumpHref({ kind: "ayah", surah: 2, ayah: 255 })).toBe(
      "/surah/2?ayah=255"
    );
  });

  it("points a surah target at the surah page", () => {
    expect(jumpHref({ kind: "surah", surah: 36 })).toBe("/surah/36");
  });

  it("has no local answer for a page or juz", () => {
    // Only the backend knows which verse opens a mushaf page.
    expect(jumpHref({ kind: "page", page: 604 })).toBeNull();
    expect(jumpHref({ kind: "juz", juz: 30 })).toBeNull();
  });
});
