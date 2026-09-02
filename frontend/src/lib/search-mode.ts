/**
 * The two search modes and how they travel: `?mode=` in the URL, and the
 * reader's last choice in localStorage so the landing box opens the way they
 * left it.
 *
 * `exact` («بحث دقيق») is the strict phrase search that has always existed;
 * `smart` («بحث ذكي») asks the archive a question and gets a cited answer.
 * Absence of the parameter means exact, so every existing link keeps working.
 */

export type SearchMode = "exact" | "smart";
export type SearchKindParam = "recitation" | "khawatir" | "all" | undefined;

export const SEARCH_MODE_KEY = "search:mode";

export const MODE_LABEL: Record<SearchMode, string> = {
  exact: "بحث دقيق",
  smart: "بحث ذكي",
};

export const SEARCH_PLACEHOLDER: Record<SearchMode, string> = {
  exact: "ابحث بآيةٍ أو كلمةٍ أو موضوع…",
  smart: "اسأل عمّا قاله الشيخ… مثلًا: ما رأي الشيخ في الصبر عند الصدمة؟",
};

/** `"smart"` only when the raw value says so; anything else is exact. */
export function parseSearchMode(raw: string | string[] | null | undefined): SearchMode {
  const value = Array.isArray(raw) ? raw[0] : raw;
  return value === "smart" ? "smart" : "exact";
}

/** The mode the reader last used, or exact when nothing usable is stored. */
export function readStoredMode(): SearchMode {
  try {
    return parseSearchMode(window.localStorage.getItem(SEARCH_MODE_KEY));
  } catch {
    return "exact";
  }
}

export function storeMode(mode: SearchMode): void {
  try {
    window.localStorage.setItem(SEARCH_MODE_KEY, mode);
  } catch {
    // Private mode or a full quota: the URL still carries the choice.
  }
}

/**
 * The `/search` URL for a query. `kind` is omitted when it is `all` or
 * absent, `mode` when it is exact — the URL only says what departs from the
 * defaults, so exact-mode links look exactly as they always have.
 */
export function searchHref(q: string, kind: SearchKindParam, mode: SearchMode = "exact"): string {
  const params = new URLSearchParams({ q });
  if (kind && kind !== "all") params.set("kind", kind);
  if (mode === "smart") params.set("mode", "smart");
  return `/search?${params.toString()}`;
}
