/**
 * Parsing a typed Quran reference into a place to go — pure, no DOM, no React.
 *
 * The surah index has one text box. It always filters the 114 cards, but when
 * what you typed also names a *specific* place — `2:255`, `صفحة ٦٠٤`,
 * `جزء ٣٠`, `البقرة ٢٥٥` — the page offers to jump straight there. This module
 * decides whether it does, and where to.
 *
 * Rule 2 (CLAUDE.md) is why every comparison here runs through
 * `normalizeForIndex`: it folds Arabic-Indic digits to ASCII (so `٢٥٥` and
 * `255` are one input), collapses whitespace, and folds hamza/ta-marbuta, so
 * `الفاتحة` and `الفاتحه` are the same surah. Raw Arabic is never compared.
 *
 * Numbers are validated against the real corpus, not just a range: `البقرة 300`
 * resolves to nothing because Al-Baqarah ends at 286. An unparseable or
 * out-of-range input returns null, and the caller simply filters the grid.
 */

import { normalizeForIndex } from "@/lib/arabic";

/** The slice of a surah row this module needs. */
export interface SurahRef {
  number: number;
  /** `name_ar` already passed through `normalize_for_index` server-side. */
  name_ar_plain: string;
  ayah_count: number;
}

export type JumpTarget =
  | { kind: "ayah"; surah: number; ayah: number }
  | { kind: "surah"; surah: number }
  | { kind: "page"; page: number }
  | { kind: "juz"; juz: number };

/** Madani mushaf pages, the numbering `Ayah.page` uses. */
export const MAX_MUSHAF_PAGE = 604;

/** Juz count. */
export const MAX_JUZ = 30;

// ---------------------------------------------------------------------------
// Grammar
// ---------------------------------------------------------------------------

/**
 * `2:255`, with any spacing. Digits are already ASCII by the time this runs.
 */
const NUMERIC_REFERENCE = /^(\d{1,3})\s*:\s*(\d{1,3})$/u;

/**
 * Mushaf page. `صفحة` normalizes to `صفحه` (ta marbuta folds), so both
 * spellings land on the same key.
 *
 * The bare `ص` abbreviation is deliberately NOT accepted: ص is also the name
 * of surah 38, so `ص ٣٨` would be unresolvably ambiguous between "page 38" and
 * "Saad, ayah 38". Spelling the word out costs three letters and removes the
 * guess.
 */
const PAGE_REFERENCE = /^(?:الصفحه|صفحه|page|pg)\s*(\d{1,3})$/u;

/** Juz. `جزء` has no surah-name collision, so the short forms are safe. */
const JUZ_REFERENCE = /^(?:الجزء|جزء|جز|juz)\s*(\d{1,2})$/u;

/** A bare number, read as a surah — see `parseJump`'s ambiguity note. */
const BARE_NUMBER = /^(\d{1,3})$/u;

/**
 * Words a reader sprinkles in that carry no reference of their own. Spelled in
 * their normalized form only — `سورة`, `آية` and `اية` all fold to these.
 */
const FILLERS = /^(?:سوره|ايه|رقم)\s+/u;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** `ال`-insensitive comparison key for a surah name. */
function nameKey(normalized: string): string {
  return normalized.startsWith("ال") ? normalized.slice(2) : normalized;
}

function findSurahByName(
  normalized: string,
  surahs: readonly SurahRef[]
): SurahRef | null {
  if (normalized === "") return null;
  const key = nameKey(normalized);
  return (
    surahs.find((surah) => nameKey(surah.name_ar_plain) === key) ?? null
  );
}

function findSurahByNumber(
  number: number,
  surahs: readonly SurahRef[]
): SurahRef | null {
  return surahs.find((surah) => surah.number === number) ?? null;
}

/** An ayah target, but only if that verse actually exists. */
function ayahTarget(surah: SurahRef | null, ayah: number): JumpTarget | null {
  if (surah === null || ayah < 1 || ayah > surah.ayah_count) return null;
  return { kind: "ayah", surah: surah.number, ayah };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Where `input` points, or null when it names no single place.
 *
 * **Ambiguity:** a bare number is always a surah. `30` is Ar-Rum, not juz 30 —
 * it preserves what the index's number filter has always meant, and juz and
 * page both have an unambiguous spelled-out prefix when that is what you want.
 */
export function parseJump(
  input: string,
  surahs: readonly SurahRef[]
): JumpTarget | null {
  let text = normalizeForIndex(input);
  if (text === "") return null;

  const numeric = NUMERIC_REFERENCE.exec(text);
  if (numeric !== null) {
    const surah = findSurahByNumber(Number(numeric[1]), surahs);
    return ayahTarget(surah, Number(numeric[2]));
  }

  const page = PAGE_REFERENCE.exec(text);
  if (page !== null) {
    const value = Number(page[1]);
    return value >= 1 && value <= MAX_MUSHAF_PAGE
      ? { kind: "page", page: value }
      : null;
  }

  const juz = JUZ_REFERENCE.exec(text);
  if (juz !== null) {
    const value = Number(juz[1]);
    return value >= 1 && value <= MAX_JUZ ? { kind: "juz", juz: value } : null;
  }

  // "سورة البقرة" and "البقرة آية 255" mean the same as the bare forms.
  text = text.replace(FILLERS, "").trim();
  if (text === "") return null;

  const bare = BARE_NUMBER.exec(text);
  if (bare !== null) {
    const surah = findSurahByNumber(Number(bare[1]), surahs);
    return surah === null ? null : { kind: "surah", surah: surah.number };
  }

  // "<name> <ayah>", the trailing number split off the name.
  const trailing = /^(.*?)\s+(?:ايه\s+|رقم\s+)?(\d{1,3})$/u.exec(text);
  if (trailing !== null) {
    const surah = findSurahByName(trailing[1].trim(), surahs);
    if (surah !== null) return ayahTarget(surah, Number(trailing[2]));
  }

  const named = findSurahByName(text, surahs);
  return named === null ? null : { kind: "surah", surah: named.number };
}

/**
 * The route a resolved target points at.
 *
 * `page` and `juz` are missing here on purpose: only the backend knows which
 * verse opens a mushaf page, so those go through `GET /api/quran/locate/`
 * first and come back as an `ayah` target.
 */
export function jumpHref(target: JumpTarget): string | null {
  switch (target.kind) {
    case "ayah":
      return `/surah/${target.surah}?ayah=${target.ayah}`;
    case "surah":
      return `/surah/${target.surah}`;
    default:
      return null;
  }
}
