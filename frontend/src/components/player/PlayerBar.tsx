"use client";

import Link from "next/link";
import { useState } from "react";
import { useAudioStore } from "@/lib/audio-store";
import type { PlaybackRate } from "@/lib/audio-store";
import { formatMs } from "@/lib/format";

const RATES: PlaybackRate[] = [0.75, 1, 1.25, 1.5];
const SLEEP_OPTIONS = [15, 30, 60] as const;

/**
 * The transport bar. Mounted once in the root layout so navigation never
 * unmounts it — playback and its controls outlive every route change.
 * Renders nothing until a track is loaded.
 */
export default function PlayerBar() {
  const current = useAudioStore((s) => s.current);
  const isPlaying = useAudioStore((s) => s.isPlaying);
  const positionMs = useAudioStore((s) => s.positionMs);
  const rate = useAudioStore((s) => s.rate);
  const sleepTimerHandle = useAudioStore((s) => s.sleepTimerHandle);
  const toggle = useAudioStore((s) => s.toggle);
  const seekMs = useAudioStore((s) => s.seekMs);
  const setRate = useAudioStore((s) => s.setRate);
  const setSleepTimer = useAudioStore((s) => s.setSleepTimer);

  const [sleepMinutes, setSleepMinutes] = useState<number | null>(null);

  // The store owns the truth: it clears its handle when the timer fires, so
  // the menu snaps back to "off" without an effect to keep the two in sync.
  const selectedSleep =
    sleepTimerHandle !== null && sleepMinutes !== null
      ? String(sleepMinutes)
      : "off";

  if (current === null) return null;

  const cycleRate = () => {
    const next = RATES[(RATES.indexOf(rate) + 1) % RATES.length];
    setRate(next);
  };

  const onSleepChange = (value: string) => {
    const minutes = value === "off" ? null : Number(value);
    setSleepMinutes(minutes);
    setSleepTimer(minutes);
  };

  return (
    <div
      className="fixed inset-x-0 bottom-0 z-50 border-t border-[var(--color-border)] bg-[var(--color-surface)]/90 backdrop-blur-[8px]"
      style={{ minHeight: "var(--player-bar-height)" }}
    >
      <div className="reading-column flex flex-wrap items-center gap-x-3 gap-y-2 py-2">
        <button
          type="button"
          onClick={toggle}
          aria-label={isPlaying ? "إيقاف مؤقت" : "تشغيل"}
          className="shrink-0 rounded border border-[var(--color-border)] px-3 py-1.5 text-sm"
        >
          {isPlaying ? "❚❚" : "▶"}
        </button>

        <span
          dir="ltr"
          className="shrink-0 text-xs tabular-nums text-[var(--color-ink-muted)]"
        >
          {formatMs(positionMs)} / {formatMs(current.durationMs)}
        </span>

        <input
          type="range"
          min={0}
          max={Math.max(1, current.durationMs)}
          step={1000}
          value={Math.min(positionMs, current.durationMs)}
          onChange={(event) => seekMs(Number(event.target.value))}
          aria-label="موضع التشغيل"
          className="order-last w-full min-w-0 basis-full accent-[var(--color-accent)] sm:order-none sm:basis-auto sm:flex-1"
        />

        <button
          type="button"
          onClick={cycleRate}
          aria-label="سرعة التشغيل"
          className="shrink-0 rounded border border-[var(--color-border)] px-2 py-1.5 text-xs text-[var(--color-ink-muted)]"
        >
          <span dir="ltr">{rate}×</span>
        </button>

        <select
          value={selectedSleep}
          onChange={(event) => onSleepChange(event.target.value)}
          aria-label="مؤقّت النوم"
          className="shrink-0 rounded border border-[var(--color-border)] bg-transparent px-2 py-1.5 text-xs text-[var(--color-ink-muted)]"
        >
          <option value="off">مؤقّت النوم</option>
          {SLEEP_OPTIONS.map((minutes) => (
            <option key={minutes} value={minutes}>
              {minutes} دقيقة
            </option>
          ))}
        </select>

        <Link
          href={`/listen/${current.segmentId}`}
          className="min-w-0 flex-1 truncate text-xs text-[var(--color-ink-muted)] sm:max-w-[14rem]"
        >
          {current.title}
        </Link>
      </div>
    </div>
  );
}
