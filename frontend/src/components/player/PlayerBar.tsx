"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useAudioStore } from "@/lib/audio-store";
import type { PlaybackRate, Track } from "@/lib/audio-store";
import { formatMs } from "@/lib/format";

const RATES: PlaybackRate[] = [0.75, 1, 1.25, 1.5];
const SLEEP_OPTIONS = [15, 30, 60] as const;

/**
 * The transport bar. Mounted once in the root layout so navigation never
 * unmounts it — playback and its controls outlive every route change.
 * Renders nothing until a track is loaded; the shell remounts per track so
 * the entrance animation and the height measurement re-run per segment.
 */
export default function PlayerBar() {
  const current = useAudioStore((s) => s.current);
  if (current === null) return null;
  return <PlayerBarShell key={current.segmentId} track={current} />;
}

/**
 * Writes the bar's exact pixel height into `--player-bar-height` on <html>
 * so `.page-shell` (and every other fixed element positioned off that var)
 * reserves precisely the room the wrapped bar occupies — short verses can no
 * longer slide underneath it. Cleanup restores the stylesheet fallback.
 */
function useSyncBarHeight(ref: React.RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const root = document.documentElement;
    const apply = () =>
      root.style.setProperty("--player-bar-height", `${el.offsetHeight}px`);
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(el);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--player-bar-height");
    };
  }, [ref]);
}

/** Four gilded bars breathing with the audio, motion-gated in CSS. */
function Equalizer({ playing }: { playing: boolean }) {
  return (
    <span aria-hidden className="player-eq hidden sm:flex" data-playing={playing}>
      <i />
      <i />
      <i />
      <i />
    </span>
  );
}

function PlayerBarShell({ track }: { track: Track }) {
  const isPlaying = useAudioStore((s) => s.isPlaying);
  const positionMs = useAudioStore((s) => s.positionMs);
  const rate = useAudioStore((s) => s.rate);
  const sleepTimerHandle = useAudioStore((s) => s.sleepTimerHandle);
  const toggle = useAudioStore((s) => s.toggle);
  const seekMs = useAudioStore((s) => s.seekMs);
  const setRate = useAudioStore((s) => s.setRate);
  const setSleepTimer = useAudioStore((s) => s.setSleepTimer);

  const [sleepMinutes, setSleepMinutes] = useState<number | null>(null);
  const barRef = useRef<HTMLDivElement | null>(null);
  useSyncBarHeight(barRef);

  // The store owns the truth: it clears its handle when the timer fires, so
  // the menu snaps back to "off" without an effect to keep the two in sync.
  const selectedSleep =
    sleepTimerHandle !== null && sleepMinutes !== null
      ? String(sleepMinutes)
      : "off";

  const cycleRate = () => {
    const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
    setRate(next);
  };

  const onSleepChange = (value: string) => {
    const minutes = value === "off" ? null : Number(value);
    setSleepMinutes(minutes);
    setSleepTimer(minutes);
  };

  const durationMs = Math.max(1, track.durationMs);
  const clampedPosition = Math.min(positionMs, durationMs);
  const seekPct = Math.min(100, (clampedPosition / durationMs) * 100);

  return (
    <div
      ref={barRef}
      role="region"
      aria-label="مشغّل الصوت"
      className="player-bar player-bar-enter fixed inset-x-0 bottom-0 z-50"
    >
      {/* The seek ribbon rides the bar's top edge: thin at rest, its gold
          thumb surfaces on hover/focus. Still a native range input, so
          keyboard seeking (arrows) keeps working. */}
      <input
        type="range"
        min={0}
        max={durationMs}
        step={1000}
        value={clampedPosition}
        onChange={(event) => seekMs(Number(event.target.value))}
        aria-label="موضع التشغيل"
        className="player-seek"
        style={{ "--seek-pct": `${seekPct}%` } as React.CSSProperties}
      />

      <div className="reading-column flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5 sm:gap-x-4">
        <button
          type="button"
          onClick={toggle}
          aria-label={isPlaying ? "إيقاف مؤقت" : "تشغيل"}
          className="player-play"
        >
          {/* Inline SVG: the text glyphs "▶"/"❚❚" render inconsistently
              across platforms (some fall back to emoji). */}
          {isPlaying ? (
            <svg
              viewBox="0 0 12 12"
              width="13"
              height="13"
              aria-hidden
              className="fill-current"
            >
              <rect x="1.5" y="1" width="3.5" height="10" rx="0.5" />
              <rect x="7" y="1" width="3.5" height="10" rx="0.5" />
            </svg>
          ) : (
            <svg
              viewBox="0 0 12 12"
              width="13"
              height="13"
              aria-hidden
              className="fill-current"
            >
              <path d="M2.5 1.2v9.6L10.5 6z" />
            </svg>
          )}
        </button>

        <Equalizer playing={isPlaying} />

        <span dir="ltr" className="player-time">
          {formatMs(clampedPosition)} / {formatMs(track.durationMs)}
        </span>

        <Link
          href={`/listen/${track.segmentId}`}
          className="player-title order-last basis-full text-center sm:order-none sm:basis-auto sm:flex-1 sm:text-start"
        >
          {track.title}
        </Link>

        <button
          type="button"
          onClick={cycleRate}
          aria-label="سرعة التشغيل"
          className="player-chip"
        >
          <span dir="ltr">{rate}×</span>
        </button>

        <select
          value={selectedSleep}
          onChange={(event) => onSleepChange(event.target.value)}
          aria-label="مؤقّت النوم"
          className="player-chip"
        >
          <option value="off">مؤقّت النوم</option>
          {SLEEP_OPTIONS.map((minutes) => (
            <option key={minutes} value={minutes}>
              {minutes} دقيقة
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
