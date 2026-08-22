"use client";

import { useEffect, useState } from "react";
import { getAyah } from "@/lib/api";
import { MAX_INTERLEAVE_AYAHS } from "@/lib/ayah-match";
import { toArabicIndic } from "@/lib/format";

interface SegmentAyahTextProps {
  surah: number;
  ayahStart: number;
  ayahEnd: number;
}

interface VerifiedAyah {
  number: number;
  text: string;
}

/**
 * The verified Tanzil text of the ayahs this segment covers, rendered above
 * the machine transcript — CLAUDE.md rule 1: Quran text never comes from
 * ASR output, and the two must never be visually conflated.
 *
 * Progressive: silent until it arrives, silent on failure, skipped offline
 * where the request cannot succeed. Over the interleave cap the fetch is
 * skipped outright. Rendered as an illuminated card (`.listen-ayah-card`)
 * so the verified text reads as the page's anchor, not a transcript row.
 */
export default function SegmentAyahText({
  surah,
  ayahStart,
  ayahEnd,
}: SegmentAyahTextProps) {
  const [ayahs, setAyahs] = useState<VerifiedAyah[] | null>(null);

  useEffect(() => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) return;
    const span = ayahEnd - ayahStart + 1;
    if (span < 1 || span > MAX_INTERLEAVE_AYAHS) return;

    let cancelled = false;
    void (async () => {
      try {
        const details = await Promise.all(
          Array.from({ length: span }, (_, k) => getAyah(surah, ayahStart + k))
        );
        if (!cancelled) {
          setAyahs(
            details.map((detail) => ({
              number: detail.number,
              text: detail.text_uthmani,
            }))
          );
        }
      } catch {
        // Quiet by design — the transcript below is the page's core.
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [surah, ayahStart, ayahEnd]);

  if (ayahs === null) return null;

  return (
    <figure className="listen-ayah-card">
      {/* Frame corner flourishes — the ayah reads like a mushaf margin note. */}
      <span aria-hidden className="listen-hero-corner end-3 top-3">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M23 1 H9 Q1 1 1 9 V23" strokeWidth="1.4" />
          <circle cx="23" cy="1" r="1.3" fill="currentColor" stroke="none" />
          <circle cx="1" cy="23" r="1.3" fill="currentColor" stroke="none" />
        </svg>
      </span>
      <span aria-hidden className="listen-hero-corner start-3 top-3 -scale-x-100">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M23 1 H9 Q1 1 1 9 V23" strokeWidth="1.4" />
          <circle cx="23" cy="1" r="1.3" fill="currentColor" stroke="none" />
          <circle cx="1" cy="23" r="1.3" fill="currentColor" stroke="none" />
        </svg>
      </span>

      <blockquote className="quran-text relative text-2xl leading-[2.2] text-[var(--lp-quran-ink)] sm:text-[1.75rem]">
        {ayahs.map((ayah) => (
          <span key={ayah.number}>
            {ayah.text}{" "}
            <span className="whitespace-nowrap text-lg text-[var(--lp-gold)]">
              ﴿{toArabicIndic(ayah.number)}﴾
            </span>{" "}
          </span>
        ))}
      </blockquote>

      <figcaption className="relative mt-3 flex items-center justify-center gap-2 text-xs text-[var(--color-ink-faint)]">
        <span aria-hidden className="text-[var(--lp-gold)]">
          ✦
        </span>
        النص القرآني الموثّق — ليس من التفريغ الآلي
      </figcaption>
    </figure>
  );
}
