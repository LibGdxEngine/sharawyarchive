/**
 * Word-snapped clip trimming — pure, no DOM, no React.
 *
 * The verse page's clip modal trims by WORDS, not by the waveform: the trim
 * follows what was said. The API enforces a one-second floor
 * (lib/clip-range.ts) and nothing above it, so every movement here lands on a
 * word boundary AND tries to keep the resulting time span legal. Word gaps are
 * discrete, so a legal span is not always reachable — `trimTimesMs` is the
 * truth the modal checks before allowing submit.
 *
 * All values are integer milliseconds (CLAUDE.md rule 5); word positions are
 * indices into the transcript array.
 */

import { MIN_CLIP_MS } from "@/lib/clip-range";
import type { ClipRange } from "@/lib/clip-range";
import type { WordRange } from "@/lib/correction-selection";
import type { TranscriptWord } from "@/types/models";

/** A trim in word positions, both ends inclusive. */
export interface WordTrim {
  startWord: number;
  endWord: number;
}

/** The audio span a trim covers. */
export function trimTimesMs(
  words: readonly TranscriptWord[],
  trim: WordTrim
): ClipRange {
  return { startMs: words[trim.startWord].s, endMs: words[trim.endWord].e };
}

function spanMs(
  words: readonly TranscriptWord[],
  startWord: number,
  endWord: number
): number {
  return words[endWord].e - words[startWord].s;
}

function clampIndex(value: number, lo: number, hi: number): number {
  return Math.min(Math.max(value, lo), hi);
}

/**
 * Drag the start handle to `targetWord`, holding the end still.
 *
 * The start retreats toward MIN_CLIP_MS — but is never bound by a maximum:
 * a clip may span any number of words up to the transcript.
 */
export function moveTrimStart(
  words: readonly TranscriptWord[],
  trim: WordTrim,
  targetWord: number
): WordTrim {
  const end = trim.endWord;
  let start = clampIndex(targetWord, 0, end);
  while (
    start > 0 &&
    spanMs(words, start, end) < MIN_CLIP_MS
  ) {
    start -= 1;
  }
  return { startWord: start, endWord: end };
}

/** Mirror of {@link moveTrimStart} for the end handle. */
export function moveTrimEnd(
  words: readonly TranscriptWord[],
  trim: WordTrim,
  targetWord: number
): WordTrim {
  const start = trim.startWord;
  const last = words.length - 1;
  let end = clampIndex(targetWord, start, last);
  while (
    end < last &&
    spanMs(words, start, end) < MIN_CLIP_MS
  ) {
    end += 1;
  }
  return { startWord: start, endWord: end };
}

/**
 * The trim a fresh modal opens with, seeded from a word selection.
 *
 * A selection shorter than the legal minimum grows outward — end first, then
 * start, alternating — so the reader's words stay inside the clip. There is
 * no maximum to cut back to.
 */
export function trimFromRange(
  words: readonly TranscriptWord[],
  range: WordRange
): WordTrim {
  const last = words.length - 1;
  let start = clampIndex(range.start, 0, last);
  let end = clampIndex(range.end, start, last);

  let growEnd = true;
  while (spanMs(words, start, end) < MIN_CLIP_MS && (start > 0 || end < last)) {
    const canGrowEnd = end < last;
    const canGrowStart = start > 0;
    if (!canGrowEnd && !canGrowStart) break;
    if (growEnd ? canGrowEnd : !canGrowStart) {
      end += 1;
    } else {
      start -= 1;
    }
    growEnd = !growEnd;
  }

  return { startWord: start, endWord: end };
}

/** Whether the API would accept this trim's span. */
export function isTrimLegal(
  words: readonly TranscriptWord[],
  trim: WordTrim
): boolean {
  return spanMs(words, trim.startWord, trim.endWord) >= MIN_CLIP_MS;
}

// ---------------------------------------------------------------------------
// Entering a trim by time rather than by pointing at words
// ---------------------------------------------------------------------------
//
// The composer lets a reader type `mm:ss`, capture the live playhead, or drag
// the overview strip. All three arrive as milliseconds and have to become word
// positions, because the trim is words: what gets clipped is what was said.

/**
 * Index of the word closest to `tMs`.
 *
 * Inside a word's own span that word wins; in the silence between two words the
 * nearer edge wins, so capturing the playhead during a pause snaps to whichever
 * word the listener just heard or is about to hear rather than always looking
 * backwards. Returns -1 only for an empty transcript.
 *
 * `words` must be sorted ascending by `s`; the search is binary, because this
 * runs on every frame of an overview-strip drag over ~9000 words.
 */
export function nearestWordIndex(
  words: readonly TranscriptWord[],
  tMs: number
): number {
  if (words.length === 0) return -1;

  // Last word starting at or before tMs — the same rule as findActiveWordIndex.
  let lo = 0;
  let hi = words.length - 1;
  let at = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (words[mid].s <= tMs) {
      at = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  if (at < 0) return 0; // before the first word
  if (tMs <= words[at].e) return at; // inside it
  if (at === words.length - 1) return at; // after the last word
  // In a gap: whichever edge is nearer, ties going forward.
  return tMs - words[at].e < words[at + 1].s - tMs ? at : at + 1;
}

/**
 * The word trim covering a time range.
 *
 * The ends are pulled *outward* to whole words — a clip that starts mid-word
 * would cut the Sheikh off mid-syllable — and then handed to
 * {@link trimFromRange}, so the result already satisfies the API's minimum.
 */
export function trimFromTimes(
  words: readonly TranscriptWord[],
  range: ClipRange
): WordTrim {
  const start = nearestWordIndex(words, range.startMs);
  const end = nearestWordIndex(words, range.endMs);
  return trimFromRange(words, {
    start: Math.min(start, end),
    end: Math.max(start, end),
  });
}
