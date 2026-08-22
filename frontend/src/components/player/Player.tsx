"use client";

import Link from "next/link";
import { formatMs, kindLabel, toArabicIndic } from "@/lib/format";
import ShareButton from "./ShareButton";
import OfflineButton from "./OfflineButton";
import SegmentAyahText from "./SegmentAyahText";
import TranscriptView from "./TranscriptView";
import { useLoadTrack } from "./useLoadTrack";
import type { Segment, Transcript } from "@/types/models";

interface PlayerProps {
  segment: Segment;
  /** Null when the segment has not been transcribed yet. */
  transcript: Transcript | null;
  /** Deep-link position from `?t=`, or null when absent. */
  startMs: number | null;
}

/**
 * Star-lattice band crowning the hero (and mirrored at its foot). Drawn
 * client-side because Player is a client component; colours come from the
 * `.listen-page` scope, decorations are aria-hidden.
 */
function ListenLattice({ flip = false }: { flip?: boolean }) {
  return (
    <svg
      aria-hidden
      role="presentation"
      preserveAspectRatio="xMidYMin slice"
      viewBox="0 0 336 48"
      className={`listen-hero-lattice${flip ? " listen-hero-lattice--bottom" : ""}`}
    >
      <defs>
        <g id="lp-star8">
          <rect x="-11" y="-11" width="22" height="22" />
          <rect
            x="-11"
            y="-11"
            width="22"
            height="22"
            transform="rotate(45)"
          />
          <circle r="3" />
        </g>
        <pattern
          id="lp-girih"
          width="42"
          height="42"
          patternUnits="userSpaceOnUse"
        >
          <g fill="none" stroke="currentColor" strokeWidth="1">
            <use href="#lp-star8" transform="translate(0 0)" />
            <use href="#lp-star8" transform="translate(42 0)" />
            <use href="#lp-star8" transform="translate(0 42)" />
            <use href="#lp-star8" transform="translate(42 42)" />
            <use href="#lp-star8" transform="translate(21 21)" />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#lp-girih)" />
    </svg>
  );
}

/** One mushaf-margin corner flourish (double arc + endpoint dots). */
function ListenCornerSvg() {
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

/** The four corner flourishes, mirrored into each corner of the hero panel. */
function ListenCorners() {
  return (
    <>
      <span aria-hidden className="listen-hero-corner end-3 top-3">
        <ListenCornerSvg />
      </span>
      <span aria-hidden className="listen-hero-corner start-3 top-3 -scale-x-100">
        <ListenCornerSvg />
      </span>
      <span aria-hidden className="listen-hero-corner bottom-3 end-3 -scale-y-100">
        <ListenCornerSvg />
      </span>
      <span aria-hidden className="listen-hero-corner bottom-3 start-3 scale-[-1]">
        <ListenCornerSvg />
      </span>
    </>
  );
}

/** Hairline gold rules flanking an eight-point star medallion. */
function ListenDivider() {
  return (
    <div
      aria-hidden
      role="presentation"
      className="relative mx-auto mt-4 flex max-w-64 items-center gap-4"
    >
      <span className="listen-rule" />
      <svg
        width="22"
        height="22"
        viewBox="0 0 26 26"
        fill="none"
        className="shrink-0 text-[var(--lp-gold)]"
      >
        <rect
          x="6.5"
          y="6.5"
          width="13"
          height="13"
          stroke="currentColor"
          strokeWidth="1.1"
        />
        <rect
          x="6.5"
          y="6.5"
          width="13"
          height="13"
          stroke="currentColor"
          strokeWidth="1.1"
          transform="rotate(45 13 13)"
        />
        <circle cx="13" cy="13" r="2" fill="currentColor" />
      </svg>
      <span className="listen-rule listen-rule--mirror" />
    </div>
  );
}

/**
 * Client shell for /listen/[segmentId].
 *
 * Owns nothing about playback itself — the <audio> element and the transport
 * controls live in the root layout, so arriving here (or leaving) never
 * interrupts sound. This component only points the store at this segment and
 * renders the illuminated reading column around it.
 */
export default function Player({ segment, transcript, startMs }: PlayerProps) {
  useLoadTrack(segment, startMs);

  const ayahRangeDisplay =
    segment.ayah_start === segment.ayah_end
      ? `الآية ${toArabicIndic(segment.ayah_start)}`
      : `الآيات ${toArabicIndic(segment.ayah_start)}–${toArabicIndic(
          segment.ayah_end
        )}`;

  return (
    <article className="reading-column page-shell pt-8">
      <header className="listen-hero">
        <ListenLattice />
        <ListenLattice flip />
        <ListenCorners />
        <span aria-hidden className="listen-hero-halo" />

        <p className="listen-kicker">
          <Link
            href={`/surah/${segment.surah}?ayah=${segment.ayah_start}`}
            className="underline-offset-4 hover:underline"
          >
            سورة {segment.surah} · {ayahRangeDisplay}
          </Link>
        </p>

        <h1 className="listen-title [font-family:var(--font-amiri)]">
          {segment.title}
        </h1>

        <ListenDivider />

        <ul className="relative mt-5 flex flex-wrap items-center justify-center gap-2">
          <li className="listen-badge listen-badge--gold">
            {kindLabel(segment.kind)}
          </li>
          <li className="listen-badge">
            المدة{" "}
            <span dir="ltr" className="tabular-nums">
              {formatMs(segment.duration_ms)}
            </span>
          </li>
          <li className="listen-badge">{segment.source.title}</li>
        </ul>

        <div className="relative mt-5 flex flex-wrap items-center justify-center gap-3">
          <ShareButton segmentId={segment.id} />
          {/* Clip karaoke and offline saving both need transcript words. */}
          {transcript !== null ? (
            <Link
              href={`/listen/${segment.id}/clip`}
              className="listen-chip"
            >
              مقطع للمشاركة
            </Link>
          ) : null}
        </div>
      </header>

      <SegmentAyahText
        key={`ayahs-${segment.id}`}
        surah={segment.surah}
        ayahStart={segment.ayah_start}
        ayahEnd={segment.ayah_end}
      />

      {transcript !== null ? (
        <div className="listen-body">
          <div className="listen-note">
            <p className="text-xs leading-relaxed text-[var(--color-ink-muted)]">
              النص مُفرَّغ آليًا وقد يحتوي على أخطاء — نص القرآن الكريم ليس من
              التفريغ الآلي
              {transcript.is_human_reviewed ? (
                <span className="mx-2 inline-block rounded border border-[var(--lp-card-border)] px-1.5 py-0.5 text-[var(--color-ink-faint)]">
                  مُراجَع
                </span>
              ) : null}
            </p>
            <OfflineButton key={segment.id} segment={segment} />
          </div>

          <div className="mt-5">
            <TranscriptView segmentId={segment.id} words={transcript.words} />
          </div>

          <details className="mt-6 text-xs text-[var(--color-ink-faint)]">
            <summary className="cursor-pointer underline-offset-4 hover:underline">
              بيانات التفريغ
            </summary>
            <p className="mt-1">
              عدد الكلمات {transcript.words.length} · إصدار التفريغ{" "}
              {transcript.version} · {transcript.engine}
            </p>
          </details>
        </div>
      ) : (
        <div className="listen-body">
          <div className="listen-note">
            <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
              لم يُفرَّغ هذا المقطع بعد — التفريغ الآلي قيد الإعداد. يمكنك
              الاستماع الآن، وسيظهر النص مع إبراز الكلمات فور اكتماله.
            </p>
          </div>
        </div>
      )}
    </article>
  );
}
