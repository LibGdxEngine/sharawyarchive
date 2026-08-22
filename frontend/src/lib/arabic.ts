/**
 * Arabic text normalization — TS port of `backend/corpus/arabic.py`.
 *
 * The verse page matches verified ayah text against ASR transcript words, and
 * rule 2 (CLAUDE.md) forbids comparing raw Arabic strings. Both sides of that
 * comparison go through THIS module, so internal consistency is what decides
 * match quality; parity with the Python implementation is still enforced
 * mechanically by `arabic.test.ts`, which runs the same fixture file the
 * backend suite uses (`normalization_pairs.json`, byte-identical copies —
 * see `backend/corpus/tests/test_frontend_fixture_sync.py`).
 *
 * Spec (same eight steps as the Python module):
 *   1. NFC normalize
 *   2. strip tatweel U+0640
 *   3. strip harakat U+064B-U+0655, dagger alif U+0670, Quranic annotation
 *      marks U+06D6-U+06ED
 *   4. أ إ آ ٱ ٲ ٳ → ا          (index only)
 *   5. ة → ه                    (index only)
 *   6. ى → ي                    (index only)
 *   7. ؤ → و ,  ئ → ي           (index only)
 *   8. collapse whitespace, Arabic-Indic digits → ASCII (index only)
 */

// --- Steps 2/3: codepoints removed outright --------------------------------

const TATWEEL = 0x0640;
const SUPERSCRIPT_ALEF = 0x0670;

const STRIPPED = new Set<number>([TATWEEL, SUPERSCRIPT_ALEF]);
// Harakat U+064B-U+0652 plus combining maddah/hamza U+0653-U+0655.
for (let cp = 0x064b; cp <= 0x0655; cp += 1) STRIPPED.add(cp);
// Quranic annotation marks U+06D6-U+06ED.
for (let cp = 0x06d6; cp <= 0x06ed; cp += 1) STRIPPED.add(cp);

// --- Steps 4-7: letter folds (index only) -----------------------------------

const LETTER_FOLDS = new Map<number, string>([
  [0x0622, "ا"], // آ ALEF WITH MADDA ABOVE
  [0x0623, "ا"], // أ ALEF WITH HAMZA ABOVE
  [0x0625, "ا"], // إ ALEF WITH HAMZA BELOW
  [0x0671, "ا"], // ٱ ALEF WASLA
  [0x0672, "ا"], // ٲ ALEF WITH WAVY HAMZA ABOVE
  [0x0673, "ا"], // ٳ ALEF WITH WAVY HAMZA BELOW
  [0x0629, "ه"], // ة TA MARBUTA
  [0x0649, "ي"], // ى ALEF MAQSURA
  [0x0624, "و"], // ؤ WAW WITH HAMZA
  [0x0626, "ي"], // ئ YEH WITH HAMZA
]);

// --- Step 8: digit folds (index only) ---------------------------------------

const DIGIT_FOLDS = new Map<number, string>();
for (let offset = 0; offset < 10; offset += 1) {
  DIGIT_FOLDS.set(0x0660 + offset, String(offset)); // ٠-٩
  DIGIT_FOLDS.set(0x06f0 + offset, String(offset)); // ۰-۹
}

function translate(s: string, folds: Map<number, string> | null): string {
  let out = "";
  for (const ch of s) {
    const cp = ch.codePointAt(0) as number;
    if (STRIPPED.has(cp)) continue;
    if (folds !== null) {
      const fold = folds.get(cp);
      if (fold !== undefined) {
        out += fold;
        continue;
      }
    }
    out += ch;
  }
  return out;
}

const INDEX_FOLDS = new Map<number, string>([...LETTER_FOLDS, ...DIGIT_FOLDS]);

/**
 * Steps 1-3 only. Display fallback: keeps letter identity (آ stays آ, ة stays
 * ة) while dropping vowel marks and Quranic annotation. Whitespace untouched.
 * Never use for comparison.
 */
export function normalizeLight(s: string): string {
  return translate(s.normalize("NFC"), null);
}

/**
 * The canonical comparison form — all eight steps. Mirrors
 * `corpus.arabic.normalize_for_index` (whitespace runs collapse to a single
 * space, result trimmed).
 */
export function normalizeForIndex(s: string): string {
  const folded = translate(s.normalize("NFC"), INDEX_FOLDS);
  return folded.split(/\s+/u).filter(Boolean).join(" ");
}

/** `normalizeForIndex` split into tokens; empty input yields no tokens. */
export function tokenizeNormalized(s: string): string[] {
  const normalized = normalizeForIndex(s);
  return normalized === "" ? [] : normalized.split(" ");
}
