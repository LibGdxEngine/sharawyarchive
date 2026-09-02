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

/**
 * Inverse of {@link formatMs} for the composer's editable time fields.
 *
 * Accepts `ss`, `mm:ss` and `h:mm:ss`, with or without padding, and tolerates
 * Arabic-Indic digits and the Arabic decimal separator a phone keyboard may
 * produce. Returns null for anything it cannot read, so the caller can leave
 * the reader's half-typed text alone instead of snapping it to zero.
 */
export function parseMs(text: string): number | null {
  const ascii = text
    .trim()
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[٫٬.,]/g, ":");
  if (ascii === "" || !/^\d{1,3}(:\d{1,2}){0,2}$/.test(ascii)) return null;

  const parts = ascii.split(":").map(Number);
  const [hours, minutes, seconds] =
    parts.length === 3
      ? parts
      : parts.length === 2
        ? [0, parts[0], parts[1]]
        : [0, 0, parts[0]];
  // Only the leading field may exceed its base: "90:00" is a legitimate way to
  // say an hour and a half into an 84-minute segment.
  if (parts.length > 1 && seconds > 59) return null;
  if (parts.length > 2 && minutes > 59) return null;
  return (hours * 3600 + minutes * 60 + seconds) * 1000;
}
