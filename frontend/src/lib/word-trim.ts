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
