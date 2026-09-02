import { describe, expect, it } from "vitest";
import type { Surah } from "@/types/models";
import {
  activeFilterCount,
  EMPTY_FILTERS,
  filterSurahs,
  filtersFromParams,
  filtersToParams,
  type SurahFilters,
} from "./surah-filter";

function surah(overrides: Partial<Surah> & Pick<Surah, "number">): Surah {
  return {
    name_ar: "سورة",
    name_ar_plain: "سوره",
    name_en: "Surah",
    ayah_count: 10,
    revelation_place: "makkah",
    segment_count: 0,
    juz_start: 1,
    juz_end: 1,
    page_start: 1,
    page_end: 1,
    ...overrides,
  };
}

const FATIHAH = surah({
  number: 1,
  name_ar: "الفاتحة",
  name_ar_plain: "الفاتحه",
  ayah_count: 7,
  revelation_place: "makkah",
  segment_count: 3,
  juz_start: 1,
  juz_end: 1,
  page_start: 1,
  page_end: 1,
});

const BAQARAH = surah({
  number: 2,
  name_ar: "البقرة",
  name_ar_plain: "البقره",
  ayah_count: 286,
  revelation_place: "madinah",
  segment_count: 0,
  juz_start: 1,
  juz_end: 3,
  page_start: 2,
  page_end: 49,
});

const NAAS = surah({
  number: 114,
  name_ar: "الناس",
  name_ar_plain: "الناس",
  ayah_count: 6,
  revelation_place: "makkah",
  segment_count: 1,
  juz_start: 30,
  juz_end: 30,
  page_start: 604,
  page_end: 604,
});

const ALL = [FATIHAH, BAQARAH, NAAS];

function withFilters(overrides: Partial<SurahFilters>): SurahFilters {
  return { ...EMPTY_FILTERS, ...overrides };
}

function numbers(rows: readonly Surah[]): number[] {
  return rows.map((row) => row.number);
}

describe("filterSurahs", () => {
  it("returns everything when nothing is set", () => {
    expect(filterSurahs(ALL, EMPTY_FILTERS)).toEqual(ALL);
  });

  it("matches a name however it is spelled", () => {
    for (const spelling of ["البقرة", "البقره", "بقر"]) {
      expect(numbers(filterSurahs(ALL, withFilters({ q: spelling })))).toEqual([
        2,
      ]);
    }
  });

  it("matches a surah number, in either digit system", () => {
    expect(numbers(filterSurahs(ALL, withFilters({ q: "114" })))).toEqual([114]);
    expect(numbers(filterSurahs(ALL, withFilters({ q: "١١٤" })))).toEqual([114]);
  });

  it("filters by revelation place", () => {
    expect(
      numbers(filterSurahs(ALL, withFilters({ place: "madinah" })))
    ).toEqual([2]);
    expect(numbers(filterSurahs(ALL, withFilters({ place: "makkah" })))).toEqual(
      [1, 114]
    );
  });

  it("keeps a surah whose juz span covers the asked-for juz", () => {
    // Al-Baqarah runs juz 1-3, so it belongs to juz 2 as much as juz 1.
    expect(numbers(filterSurahs(ALL, withFilters({ juz: 2 })))).toEqual([2]);
    expect(numbers(filterSurahs(ALL, withFilters({ juz: 1 })))).toEqual([1, 2]);
    expect(numbers(filterSurahs(ALL, withFilters({ juz: 30 })))).toEqual([114]);
  });

  it("keeps a surah whose page span covers the asked-for page", () => {
    expect(numbers(filterSurahs(ALL, withFilters({ page: 25 })))).toEqual([2]);
    expect(numbers(filterSurahs(ALL, withFilters({ page: 604 })))).toEqual([
      114,
    ]);
    expect(filterSurahs(ALL, withFilters({ page: 300 }))).toEqual([]);
  });

  it("combines filters conjunctively", () => {
    expect(
      numbers(filterSurahs(ALL, withFilters({ place: "makkah", juz: 30 })))
    ).toEqual([114]);
    expect(
      filterSurahs(ALL, withFilters({ place: "madinah", juz: 30 }))
    ).toEqual([]);
  });
});

describe("activeFilterCount", () => {
  it("is zero for the neutral state", () => {
    expect(activeFilterCount(EMPTY_FILTERS)).toBe(0);
  });

  it("ignores whitespace-only text", () => {
    expect(activeFilterCount(withFilters({ q: "   " }))).toBe(0);
  });

  it("counts each narrowing filter once", () => {
    expect(
      activeFilterCount(
        withFilters({ q: "يس", place: "makkah", juz: 23, page: 440 })
      )
    ).toBe(4);
  });
});

describe("URL contract", () => {
  it("omits neutral values so /surahs stays clean", () => {
    expect(filtersToParams(EMPTY_FILTERS).toString()).toBe("");
  });

  it("round-trips a full filter set", () => {
    const filters = withFilters({
      q: "البقرة",
      place: "madinah",
      juz: 2,
      page: 25,
    });

    expect(filtersFromParams(filtersToParams(filters))).toEqual(filters);
  });

  it("trims the query on the way out", () => {
    expect(filtersToParams(withFilters({ q: "  يس  " })).get("q")).toBe("يس");
  });

  it("reads the record shape a server component receives", () => {
    expect(
      filtersFromParams({ juz: "30", place: "makkah" })
    ).toEqual(withFilters({ juz: 30, place: "makkah" }));
  });

  it("takes the first value when a param repeats", () => {
    expect(filtersFromParams({ juz: ["5", "9"] }).juz).toBe(5);
  });

  it.each([
    { note: "out of range juz", params: { juz: "99" }, key: "juz" as const },
    { note: "zero page", params: { page: "0" }, key: "page" as const },
    { note: "non-numeric", params: { juz: "last" }, key: "juz" as const },
    { note: "fractional", params: { page: "1.5" }, key: "page" as const },
    { note: "empty", params: { juz: "" }, key: "juz" as const },
  ])("falls back to neutral for $note", ({ params, key }) => {
    expect(filtersFromParams(params)[key]).toBeNull();
  });

  it("falls back to 'all' for an unknown place", () => {
    expect(filtersFromParams({ place: "mars" }).place).toBe("all");
  });
});
