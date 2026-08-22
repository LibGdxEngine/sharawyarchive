/**
 * Locating recited ayahs inside an ASR transcript — pure, no DOM, no React.
 *
 * The verse page shows verified Quran text (Tanzil `text_uthmani`) as cards
 * interleaved with the machine transcript. The backend has no ayah↔audio
 * alignment (segments only carry an ayah RANGE), so the cards are placed by
 * matching normalized ayah tokens against normalized ASR tokens client-side.
 *
 * Rule 1 (CLAUDE.md) is structural here: an accepted match only decides WHERE
 * a card sits and which transcript words it replaces — the card itself always
 * renders `text_uthmani`, never the ASR words. Rule 2 is honoured by injecting
 * `normalizeForIndex` (lib/arabic.ts) for every comparison.
 *
 * Matching is Smith–Waterman local alignment per ayah (match +2, mismatch −1,
 * gap −1, "match" = exact normalized token equality), so a partially recited
 * or slightly mis-heard ayah still anchors, and pure khawatir text does not.
 * One pass is O(transcript × ayah tokens); it runs once per transcript inside
 * a useMemo, never in the highlight loop.
 */

import type { TranscriptWord } from "@/types/models";

// ---------------------------------------------------------------------------
// Tuning constants (exported for tests)
// ---------------------------------------------------------------------------

/** Minimum matched-token share of the ayah for an alignment to count. */
export const MATCH_THRESHOLD = 0.6;

/**
 * Minimum exactly-matched tokens. Guards two/three-word ayahs against noise:
 * an ayah shorter than this can never interleave and falls back to the pinned
 * card, which is the honest failure mode.
 */
export const MIN_MATCHED_TOKENS = 3;

/** How many recitations of the SAME ayah one segment may anchor. */
export const MAX_REPEATS_PER_AYAH = 6;

/**
 * Widest segment ayah-range the page will interleave. Past this, the matcher
 * is skipped entirely (the focused ayah is pinned at top instead) — a
 * recitation segment covering a whole long surah would otherwise cost
 * range × transcript alignment passes on the main thread.
 */
export const MAX_INTERLEAVE_AYAHS = 40;

// Smith–Waterman scoring.
const MATCH_SCORE = 2;
const MISMATCH_PENALTY = -1;
const GAP_PENALTY = -1;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** The slice of AyahDetail the matcher needs. */
export interface AyahRef {
  number: number;
  textUthmani: string;
}

export interface AyahTokenAlignment {
  ayahNumber: number;
  /** First transcript word index of the matched run (inclusive). */
  wordStart: number;
  /** Last transcript word index of the matched run (inclusive). */
  wordEnd: number;
  /** Exactly-matched tokens / ayah token count, 0..1. */
  score: number;
  /** Count of exactly-matched token pairs. */
  matched: number;
  /**
   * Per transcript word offset (0..wordEnd-wordStart): the index of the
   * EXACTLY matched uthmani token, or -1 where the ASR word matched nothing.
   * Only exact matches map — a mismatched-but-aligned word never points at a
   * Quran token, so the card highlight can never be a guess.
   */
  tokenMap: Int32Array;
}

export type VerseBlock =
  | {
      kind: "ayah";
      ayah: AyahRef;
      /** Null for the pinned fallback card (no located recitation). */
      match: AyahTokenAlignment | null;
    }
  | {
      kind: "tafseer";
      /** Transcript word range of this run, inclusive. */
      wordStart: number;
      wordEnd: number;
    };

// ---------------------------------------------------------------------------
// Smith–Waterman
// ---------------------------------------------------------------------------

interface LocalAlignment {
  wordStart: number;
  wordEnd: number;
  matched: number;
  tokenMap: Int32Array;
}

/** Direction codes for the traceback matrix. */
const STOP = 0;
const DIAG = 1;
const UP = 2; // gap in the ayah (skip an ASR word)
const LEFT = 3; // gap in the transcript (skip an ayah token)

/**
 * Best local alignment of `quran` inside `asr`, or null when even the best
 * cell scores zero. `asr` entries that are empty strings never match (words
 * that normalized away, or masked positions).
 */
function bestLocalAlignment(
  asr: readonly string[],
  quran: readonly string[]
): LocalAlignment | null {
  const n = asr.length;
  const m = quran.length;
  if (n === 0 || m === 0) return null;

  const width = m + 1;
  // Score needs only the previous row; traceback needs every cell.
  let prev = new Int32Array(width);
  let row = new Int32Array(width);
  const dir = new Uint8Array((n + 1) * width);

  let best = 0;
  let bestI = 0;
  let bestJ = 0;

  for (let i = 1; i <= n; i += 1) {
    const asrToken = asr[i - 1];
    for (let j = 1; j <= m; j += 1) {
      const isMatch = asrToken !== "" && asrToken === quran[j - 1];
      const diag =
        prev[j - 1] + (isMatch ? MATCH_SCORE : MISMATCH_PENALTY);
      const up = prev[j] + GAP_PENALTY;
      const left = row[j - 1] + GAP_PENALTY;

      let score = 0;
      let direction = STOP;
      if (diag >= up && diag >= left && diag > 0) {
        score = diag;
        direction = DIAG;
      } else if (up >= left && up > 0) {
        score = up;
        direction = UP;
      } else if (left > 0) {
        score = left;
        direction = LEFT;
      }

      row[j] = score;
      dir[i * width + j] = direction;
      if (score > best) {
        best = score;
        bestI = i;
        bestJ = j;
      }
    }
    const swap = prev;
    prev = row;
    row = swap;
    row.fill(0);
  }

  if (best <= 0) return null;

  // Traceback from the best cell to the first STOP.
  let i = bestI;
  let j = bestJ;
  let startI = bestI;
  const pairs: Array<{ offsetI: number; tokenJ: number }> = [];
  while (i > 0 && j > 0) {
    const direction = dir[i * width + j];
    if (direction === STOP) break;
    if (direction === DIAG) {
      if (asr[i - 1] !== "" && asr[i - 1] === quran[j - 1]) {
        pairs.push({ offsetI: i - 1, tokenJ: j - 1 });
      }
      i -= 1;
      j -= 1;
    } else if (direction === UP) {
      i -= 1;
    } else {
      j -= 1;
    }
    startI = i + 1;
  }

  const wordStart = startI - 1;
  const wordEnd = bestI - 1;
  const tokenMap = new Int32Array(wordEnd - wordStart + 1).fill(-1);
  for (const pair of pairs) {
    tokenMap[pair.offsetI - wordStart] = pair.tokenJ;
  }

  return { wordStart, wordEnd, matched: pairs.length, tokenMap };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function tokenize(normalize: (s: string) => string, text: string): string[] {
  const normalized = normalize(text);
  return normalized === "" ? [] : normalized.split(" ");
}

/**
 * Every accepted recitation span, over all `ayahs`, sorted by `wordStart`.
 *
 * Per ayah, the best local alignment is taken, its span masked, and the search
 * repeated — the Sheikh often recites the same ayah more than once, and each
 * recitation gets its own card. Overlaps between DIFFERENT ayahs' spans are
 * resolved greedily by matched-token count.
 */
export function matchAyahsInTranscript(
  ayahs: readonly AyahRef[],
  words: readonly TranscriptWord[],
  normalize: (s: string) => string
): AyahTokenAlignment[] {
  if (ayahs.length === 0 || words.length === 0) return [];

  // One token per ASR word. A word whose normalization spans several tokens
  // keeps the space-joined form and simply never equals a single ayah token.
  const asr = words.map((word) => normalize(word.t));

  const candidates: AyahTokenAlignment[] = [];

  for (const ayah of ayahs) {
    const quran = tokenize(normalize, ayah.textUthmani);
    if (quran.length === 0) continue;

    const masked = asr.slice();
    for (let repeat = 0; repeat < MAX_REPEATS_PER_AYAH; repeat += 1) {
      const alignment = bestLocalAlignment(masked, quran);
      if (alignment === null) break;
      const score = alignment.matched / quran.length;
      if (score < MATCH_THRESHOLD || alignment.matched < MIN_MATCHED_TOKENS) {
        break;
      }
      candidates.push({
        ayahNumber: ayah.number,
        wordStart: alignment.wordStart,
        wordEnd: alignment.wordEnd,
        score,
        matched: alignment.matched,
        tokenMap: alignment.tokenMap,
      });
      for (let k = alignment.wordStart; k <= alignment.wordEnd; k += 1) {
        masked[k] = "";
      }
    }
  }

  // Strongest anchors win the overlap; the rest are dropped, not trimmed.
  candidates.sort(
    (a, b) =>
      b.matched - a.matched || b.score - a.score || a.wordStart - b.wordStart
  );
  const kept: AyahTokenAlignment[] = [];
  for (const candidate of candidates) {
    const overlaps = kept.some(
      (other) =>
        candidate.wordStart <= other.wordEnd &&
        other.wordStart <= candidate.wordEnd
    );
    if (!overlaps) kept.push(candidate);
  }

  return kept.sort((a, b) => a.wordStart - b.wordStart);
}

/**
 * The interleaved page structure: tafseer runs between the ayah cards, in
 * transcript order. When the focused ayah (`pinnedAyahNumber`) found no
 * anchor, its card is pinned before everything — the page must always show
 * the verse it is about.
 */
export function buildVerseBlocks(
  words: readonly TranscriptWord[],
  ayahs: readonly AyahRef[],
  matches: readonly AyahTokenAlignment[],
  pinnedAyahNumber: number | null
): VerseBlock[] {
  const byNumber = new Map(ayahs.map((ayah) => [ayah.number, ayah]));
  const blocks: VerseBlock[] = [];

  if (pinnedAyahNumber !== null) {
    const pinned = byNumber.get(pinnedAyahNumber);
    const anchored = matches.some(
      (match) => match.ayahNumber === pinnedAyahNumber
    );
    if (pinned !== undefined && !anchored) {
      blocks.push({ kind: "ayah", ayah: pinned, match: null });
    }
  }

  const ordered = [...matches].sort((a, b) => a.wordStart - b.wordStart);
  let cursor = 0;
  for (const match of ordered) {
    const ayah = byNumber.get(match.ayahNumber);
    if (ayah === undefined) continue;
    if (match.wordStart > cursor) {
      blocks.push({ kind: "tafseer", wordStart: cursor, wordEnd: match.wordStart - 1 });
    }
    blocks.push({ kind: "ayah", ayah, match });
    cursor = match.wordEnd + 1;
  }
  if (cursor < words.length) {
    blocks.push({ kind: "tafseer", wordStart: cursor, wordEnd: words.length - 1 });
  }

  return blocks;
}

/**
 * The uthmani token to paint while transcript word `activeWordIndex` plays,
 * or -1 for card-level highlight only. Silence and unmatched words keep the
 * previous matched token lit — same convention as `findActiveWordIndex`.
 */
export function activeQuranToken(
  match: AyahTokenAlignment,
  activeWordIndex: number
): number {
  if (activeWordIndex < match.wordStart || activeWordIndex > match.wordEnd) {
    return -1;
  }
  for (let offset = activeWordIndex - match.wordStart; offset >= 0; offset -= 1) {
    const token = match.tokenMap[offset];
    if (token >= 0) return token;
  }
  return -1;
}

/**
 * Matched share of the ASR span. Below `PER_WORD_HIGHLIGHT_DENSITY` the card
 * should highlight as a whole instead of word-by-word.
 */
export function alignmentDensity(match: AyahTokenAlignment): number {
  return match.matched / (match.wordEnd - match.wordStart + 1);
}

/** Density floor for per-word highlight inside an ayah card. */
export const PER_WORD_HIGHLIGHT_DENSITY = 0.8;
