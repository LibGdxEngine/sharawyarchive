/**
 * The `/surahs` index filter — pure, no DOM, no React.
 *
 * The index is 114 cards and the whole list is already in memory, so filtering
 * is a client-side predicate rather than a query. This module owns both the
 * predicate and the URL contract (`filtersToParams`/`filtersFromParams`), so
 * the server component that reads `searchParams` and the client component that
 * writes them back cannot drift apart.
 *
 * Name matching goes through `normalizeForIndex` per rule 2 (CLAUDE.md), which
 * also folds Arabic-Indic digits — so `١٨` and `18` both find surah 18.
 */

import { normalizeForIndex } from "@/lib/arabic";
import type { Surah } from "@/types/models";

export type RevelationFilter = "all" | "makkah" | "madinah";

export interface SurahFilters {
  /** Free text: surah name or number. */
  q: string;
  place: RevelationFilter;
  /** Show only surahs whose juz span covers this juz. */
  juz: number | null;
  /** Show only surahs whose mushaf-page span covers this page. */
  page: number | null;
  /** Show only surahs that have at least one segment. */
  hasAudio: boolean;
}

export const EMPTY_FILTERS: SurahFilters = {
  q: "",
  place: "all",
  juz: null,
  page: null,
  hasAudio: false,
};

// ---------------------------------------------------------------------------
// Predicate
// ---------------------------------------------------------------------------

/**
 * Whether `[start, end]` contains `value`. Surahs straddle juz and page
 * boundaries, so "in juz 1" means the span overlaps juz 1 — the same
 * range-overlap shape the backend uses to decide which segments cover an ayah.
 */
function spanCovers(
  start: number | null | undefined,
  end: number | null | undefined,
  value: number
): boolean {
  if (start === null || start === undefined) return false;
  if (end === null || end === undefined) return false;
  return start <= value && value <= end;
}

function matchesText(surah: Surah, needle: string): boolean {
  if (needle === "") return true;
  return (
    normalizeForIndex(surah.name_ar).includes(needle) ||
    String(surah.number) === needle
  );
}

export function filterSurahs(
  surahs: readonly Surah[],
  filters: SurahFilters
): Surah[] {
  const needle = normalizeForIndex(filters.q.trim());
  return surahs.filter((surah) => {
    if (!matchesText(surah, needle)) return false;
    if (filters.place !== "all" && surah.revelation_place !== filters.place) {
      return false;
    }
    if (
      filters.juz !== null &&
      !spanCovers(surah.juz_start, surah.juz_end, filters.juz)
    ) {
      return false;
    }
    if (
      filters.page !== null &&
      !spanCovers(surah.page_start, surah.page_end, filters.page)
    ) {
      return false;
    }
    if (filters.hasAudio && surah.segment_count <= 0) return false;
    return true;
  });
}

/** How many filters are narrowing the list — drives the reset affordance. */
export function activeFilterCount(filters: SurahFilters): number {
  let count = 0;
  if (filters.q.trim() !== "") count += 1;
  if (filters.place !== "all") count += 1;
  if (filters.juz !== null) count += 1;
  if (filters.page !== null) count += 1;
  if (filters.hasAudio) count += 1;
  return count;
}

// ---------------------------------------------------------------------------
// URL contract
// ---------------------------------------------------------------------------

/** What `searchParams` looks like to a server component. */
export type RawParams =
  | URLSearchParams
  | Record<string, string | string[] | undefined>;

function readParam(params: RawParams, key: string): string | null {
  if (params instanceof URLSearchParams) return params.get(key);
  const value = params[key];
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

/** A positive integer within `[1, max]`, or null for anything else. */
function readBounded(
  params: RawParams,
  key: string,
  max: number
): number | null {
  const raw = readParam(params, key);
  if (raw === null || raw.trim() === "") return null;
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > max) return null;
  return value;
}

/** Juz numbers in the URL contract. */
export const MAX_JUZ = 30;

/** Madani mushaf pages in the URL contract. */
export const MAX_PAGE = 604;

/**
 * Filters from a URL. Anything unrecognised falls back to the neutral value —
 * a hand-edited `?juz=99` shows the full index rather than an error page.
 */
export function filtersFromParams(params: RawParams): SurahFilters {
  const place = readParam(params, "place");
  const audio = readParam(params, "audio");
  return {
    q: readParam(params, "q") ?? "",
    place: place === "makkah" || place === "madinah" ? place : "all",
    juz: readBounded(params, "juz", MAX_JUZ),
    page: readBounded(params, "page", MAX_PAGE),
    hasAudio: audio === "1",
  };
}

/** The inverse. Neutral values are omitted, so `/surahs` stays a clean URL. */
export function filtersToParams(filters: SurahFilters): URLSearchParams {
  const params = new URLSearchParams();
  const q = filters.q.trim();
  if (q !== "") params.set("q", q);
  if (filters.place !== "all") params.set("place", filters.place);
  if (filters.juz !== null) params.set("juz", String(filters.juz));
  if (filters.page !== null) params.set("page", String(filters.page));
  if (filters.hasAudio) params.set("audio", "1");
  return params;
}
