/**
 * Display formatting helpers.
 *
 * Digit policy (DESIGN.md — "Restraint", type scale row `xs`):
 * - UI chrome (player position/duration, counts, ranges) uses ASCII digits in
 *   the Plex Arabic face. They are read as machine values, they sit inside
 *   LTR-shaped constructs like `12:34`, and Plex renders them unambiguously.
 * - Quranic material (ayah numbers rendered in the Amiri Quran face) uses
 *   Arabic-Indic digits, matching mushaf convention.
 */

/** `mm:ss`, or `h:mm:ss` past one hour. Always ASCII digits. */
export function formatMs(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  const pad = (n: number) => String(n).padStart(2, "0");
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(seconds)}`
    : `${minutes}:${pad(seconds)}`;
}

const ARABIC_INDIC = ["٠", "١", "٢", "٣", "٤", "٥", "٦", "٧", "٨", "٩"];

/** ASCII digits -> Arabic-Indic. Used only for Quranic ayah numbering. */
export function toArabicIndic(value: number | string): string {
  return String(value).replace(/[0-9]/g, (d) => ARABIC_INDIC[Number(d)]);
}

/** Arabic label for a segment kind. */
export function kindLabel(kind: "recitation" | "khawatir"): string {
  return kind === "recitation" ? "تلاوة" : "خواطر";
}
