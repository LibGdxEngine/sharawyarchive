"use client";

import { useMemo } from "react";
import { normalizeForIndex } from "@/lib/arabic";
import {
  PER_WORD_HIGHLIGHT_DENSITY,
  activeQuranToken,
  alignmentDensity,
} from "@/lib/ayah-match";
import type { AyahRef, AyahTokenAlignment } from "@/lib/ayah-match";
import { toArabicIndic } from "@/lib/format";

interface AyahCardProps {
  ayah: AyahRef;
  /** Null for a pinned card — no recitation was located in the transcript. */
  match: AyahTokenAlignment | null;
  /** Live transcript word index (-1 when nothing plays). */
  activeWordIndex: number;
  /** Surah name for the reference line, e.g. "التكوير". Falls back to the number. */
  surahName: string | null;
  surahNumber: number;
  /** Seek to a transcript word (anchored cards only). */
  onSeekWord?: (wordIndex: number) => void;
}

/**
 * The verified ayah card — ALWAYS Tanzil `text_uthmani` in the Quran face
 * (CLAUDE.md rule 1; ASR words never render here). An anchored card follows
 * playback: word-by-word when the alignment is dense enough, as a whole
 * otherwise — a sparse alignment must not guess at word positions.
 */
export default function AyahCard({
  ayah,
  match,
  activeWordIndex,
  surahName,
  surahNumber,
  onSeekWord,
}: AyahCardProps) {
  // Display tokens come from the uthmani text; `tokenMap` indexes NORMALIZED
  // tokens, and uthmani has display-only tokens that normalize away (ornament
  // marks like ۞), so each display token is mapped to its normalized index.
  const tokens = useMemo(() => {
    const display = ayah.textUthmani.split(/\s+/u).filter(Boolean);
    let normIndex = 0;
    return display.map((text) => ({
      text,
      normIndex: normalizeForIndex(text) === "" ? -1 : normIndex++,
    }));
  }, [ayah.textUthmani]);

  // Normalized token index -> first transcript word that matched it, for
  // click-to-seek from inside the card.
  const tokenToWord = useMemo(() => {
    if (match === null) return null;
    const map = new Map<number, number>();
    for (let offset = 0; offset < match.tokenMap.length; offset += 1) {
      const token = match.tokenMap[offset];
      if (token >= 0 && !map.has(token)) {
        map.set(token, match.wordStart + offset);
      }
    }
    return map;
  }, [match]);

  const isCardActive =
    match !== null &&
    activeWordIndex >= match.wordStart &&
    activeWordIndex <= match.wordEnd;
  const perWord =
    match !== null && alignmentDensity(match) >= PER_WORD_HIGHLIGHT_DENSITY;
  const activeToken =
    isCardActive && perWord && match !== null
      ? activeQuranToken(match, activeWordIndex)
      : -1;

  const reference = `${surahName ?? `سورة ${surahNumber}`} ${toArabicIndic(
    ayah.number
  )}`;

  return (
    <figure
      className={`ayah-card my-6${
        isCardActive && !perWord ? " ayah-card-active" : ""
      }`}
    >
      <blockquote
        className="quran-text text-3xl leading-loose text-[var(--verse-quran-ink)]"
        lang="ar"
      >
        <span aria-hidden="true" className="text-[var(--verse-gold)]">
          ﴿
        </span>{" "}
        {tokens.map((token, position) => {
          const wordIndex =
            tokenToWord !== null && token.normIndex >= 0
              ? tokenToWord.get(token.normIndex)
              : undefined;
          const highlighted = token.normIndex >= 0 && token.normIndex === activeToken;
          const shared = highlighted
            ? "word-active"
            : "";
          return (
            <span key={position}>
              {wordIndex !== undefined && onSeekWord !== undefined ? (
                <button
                  type="button"
                  data-transcript-word=""
                  data-word-index={wordIndex}
                  onClick={() => onSeekWord(wordIndex)}
                  className={`inline cursor-pointer bg-transparent p-0 text-inherit ${shared}`}
                >
                  {token.text}
                </button>
              ) : (
                <span className={shared}>{token.text}</span>
              )}{" "}
            </span>
          );
        })}
        <span aria-hidden="true" className="text-[var(--verse-gold)]">
          ﴾
        </span>
      </blockquote>
      <figcaption className="mt-3 flex items-center justify-center gap-2.5">
        <span className="text-sm text-[var(--verse-gold)] [font-family:var(--font-amiri)]">
          {reference}
        </span>
        <span className="rounded bg-[var(--verse-gold)] px-2 py-0.5 text-[11px] font-semibold text-[var(--verse-gold-ink)]">
          آية موثّقة
        </span>
      </figcaption>
    </figure>
  );
}
