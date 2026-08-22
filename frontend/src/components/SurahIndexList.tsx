"use client";

import Link from "next/link";
import { useState } from "react";
import { normalizeForIndex } from "@/lib/arabic";
import { toArabicIndic } from "@/lib/format";
import type { Surah } from "@/types/models";

interface SurahIndexListProps {
  surahs: Surah[];
}

/**
 * Pointed mihrab arch with a hanging finial — the medallion motif for the
 * index, echoing mosque-niche architecture instead of a star.
 */
const ARCH_PATH =
  "M28 88 L28 44 C28 30 36 24 42 19 C46 15.5 50 10 50 6 C50 10 54 15.5 58 19 C64 24 72 30 72 44 L72 88 Z";
const FINIAL_PATH = "M50 0.5 L52.5 3 L50 5.5 L47.5 3 Z";

function revelationLabel(place: string): string {
  return place === "makkah" ? "مكية" : "مدنية";
}

/**
 * The surah-number medallion: a mihrab arch drawn faint by default, its inner
 * double-arch tracing the outline. On hover the arch swells slightly, fills
 * gold, and the number turns white — light filling the niche.
 */
function ArchMedallion({ number }: { number: number }) {
  return (
    <div className="relative h-16 w-16 transition-transform duration-300 group-hover:scale-105">
      <svg
        viewBox="0 0 100 100"
        aria-hidden
        className="absolute inset-0 h-full w-full overflow-visible"
      >
        <path
          d={FINIAL_PATH}
          className="fill-[var(--surah-gold)] opacity-50 transition-all duration-300 group-hover:fill-[var(--surah-gold-ink)] group-hover:opacity-100"
        />
        <path
          d={ARCH_PATH}
          className="fill-[var(--surah-gold)] stroke-none opacity-[0.13] transition-opacity duration-300 group-hover:opacity-100"
        />
        <path
          d={ARCH_PATH}
          transform="translate(50 46.5) scale(0.85) translate(-50 -46.5)"
          className="fill-none stroke-[var(--surah-gold)] stroke-[2] opacity-60 transition-opacity duration-300 group-hover:opacity-0"
        />
        <path
          d="M20 88 H80"
          className="fill-none stroke-[var(--surah-gold)] stroke-[2.5] opacity-60"
          strokeLinecap="round"
        />
      </svg>
      <span className="absolute inset-0 grid translate-y-4 place-items-center text-base font-semibold text-[var(--surah-gold-deep)] transition-colors duration-300 group-hover:text-[var(--surah-gold-ink)]">
        {toArabicIndic(number)}
      </span>
    </div>
  );
}

/** Centered arabesque divider: line, leaf-dot, diamond, leaf-dot, line. */
function Arabesque() {
  return (
    <svg
      viewBox="0 0 72 10"
      aria-hidden
      className="h-3 w-[4.5rem] text-[var(--surah-gold)] opacity-50 transition-opacity duration-300 group-hover:opacity-90"
    >
      <path d="M8 5 H28" stroke="currentColor" strokeWidth="1" />
      <path d="M44 5 H64" stroke="currentColor" strokeWidth="1" />
      <path
        d="M36 2.2 L38.8 5 L36 7.8 L33.2 5 Z"
        fill="currentColor"
      />
      <circle cx="5" cy="5" r="1.4" fill="currentColor" />
      <circle cx="67" cy="5" r="1.4" fill="currentColor" />
    </svg>
  );
}

/** One mushaf-margin corner flourish (double arc + endpoint dots). */
function CornerSvg() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden>
      <path d="M23 1 H9 Q1 1 1 9 V23" strokeWidth="1.4" />
      <path
        d="M23 5.5 H10 Q5.5 5.5 5.5 10 V23"
        strokeWidth="1.4"
        opacity="0.5"
      />
      <circle cx="23" cy="1" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="1" cy="23" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** The four corner flourishes, mirrored into each corner of the card. */
function CardCorners() {
  const base =
    "surah-corner pointer-events-none absolute h-6 w-6 text-[var(--surah-gold)]";
  return (
    <>
      <span aria-hidden className={`${base} end-2 top-2`}>
        <CornerSvg />
      </span>
      <span aria-hidden className={`${base} start-2 top-2 -scale-x-100`}>
        <CornerSvg />
      </span>
      <span aria-hidden className={`${base} bottom-2 end-2 -scale-y-100`}>
        <CornerSvg />
      </span>
      <span aria-hidden className={`${base} bottom-2 start-2 scale-[-1]`}>
        <CornerSvg />
      </span>
    </>
  );
}

function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden
      className={className}
    >
      <circle
        cx="9"
        cy="9"
        r="6"
        stroke="currentColor"
        strokeWidth="1.6"
      />
      <path
        d="M13.5 13.5 17 17"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

function ChevronLeft({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden className={className}>
      <path
        d="M10 3 5 8l5 5"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * The /surahs index: filter field + the 114-card grid, client-side so typing
 * narrows the list without a round trip. The full list still renders on the
 * server (client components SSR in App Router), so first paint and no-JS
 * browsing show every surah.
 *
 * Matching goes through normalizeForIndex (rule 2): diacritics, hamza/ta
 * marbuta folds and Arabic-Indic digits all collapse, so "يس" finds "يس"
 * with any spelling, and "١٨" or "18" finds surah 18.
 */
export default function SurahIndexList({ surahs }: SurahIndexListProps) {
  const [query, setQuery] = useState("");
  const needle = normalizeForIndex(query.trim());

  const shown =
    needle === ""
      ? surahs
      : surahs.filter(
          (surah) =>
            normalizeForIndex(surah.name_ar).includes(needle) ||
            String(surah.number) === needle
        );

  return (
    <>
      <div className="surah-search relative mt-8 rounded-full">
        <label htmlFor="surah-filter" className="sr-only">
          تصفية السور
        </label>
        <SearchIcon className="surah-search-icon pointer-events-none absolute start-5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--color-ink-faint)]" />
        <input
          id="surah-filter"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="تصفية بالاسم أو الرقم…"
          autoComplete="off"
          className="w-full bg-transparent py-2.5 pe-5 ps-12 text-sm placeholder:text-[var(--color-ink-faint)]"
        />
      </div>

      {shown.length === 0 ? (
        <p className="mt-10 text-center text-sm text-[var(--color-ink-muted)]">
          لا توجد سورة مطابقة.
        </p>
      ) : (
        <ol className="mt-8 grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-5">
          {shown.map((surah, i) => (
            <li key={surah.number}>
              <Link
                href={`/surah/${surah.number}`}
                className="surah-card group flex h-full flex-col items-center px-3 pb-4 pt-6 text-center"
                style={{ animationDelay: `${Math.min(i, 23) * 25}ms` }}
              >
                <CardCorners />
                <span
                  aria-hidden
                  className="surah-card-topglow pointer-events-none absolute inset-x-6 -top-10 h-28 opacity-0 transition-opacity duration-500 group-hover:opacity-100"
                />

                <ArchMedallion number={surah.number} />
                <span className="quran-text mt-3 text-2xl leading-[1.7] text-[var(--color-ink)] transition-colors duration-300 group-hover:text-[var(--surah-gold-deep)]">
                  {surah.name_ar}
                </span>
                <Arabesque />

                <span className="mt-auto flex flex-wrap items-center justify-center gap-1.5 pt-3">
                  <span
                    className={
                      surah.revelation_place === "makkah"
                        ? "surah-badge surah-badge--gold"
                        : "surah-badge surah-badge--green"
                    }
                  >
                    {revelationLabel(surah.revelation_place)}
                  </span>
                  <span className="surah-badge">
                    {toArabicIndic(surah.ayah_count)} آية
                  </span>
                  {surah.segment_count > 0 ? (
                    <span className="surah-badge">
                      {toArabicIndic(surah.segment_count)} مقطع
                    </span>
                  ) : null}
                </span>

                <span className="surah-card-go">
                  عرض السورة
                  <ChevronLeft className="h-3 w-3" />
                </span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}
