"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, createClip, getClip } from "@/lib/api";
import { useAudioStore } from "@/lib/audio-store";
import {
  MAX_CLIP_MS,
  MIN_CLIP_MS,
  canClipSegment,
  defaultClipRange,
  moveClipEnd,
  moveClipStart,
} from "@/lib/clip-range";
import type { ClipRange } from "@/lib/clip-range";
import { formatMs } from "@/lib/format";
import type { Clip, ClipStatus, Segment, Waveform } from "@/types/models";

interface ClipComposerProps {
  segment: Segment;
}

/** Server-side render presets — the swatches mirror what the video will look like. */
const PRESETS = [
  { id: "classic", label: "كلاسيكي", bg: "#141412", ink: "#f0ede8" },
  { id: "night", label: "ليلي", bg: "#0d2e1f", ink: "#d4eee3" },
  { id: "light", label: "فاتح", bg: "#f4f4f2", ink: "#141412" },
] as const;

type PresetId = (typeof PRESETS)[number]["id"];

const POLL_INTERVAL_MS = 3_000;
/** ~2 minutes of polling before handing the reader a link and stepping back. */
const MAX_POLLS = 40;

/** Bars drawn for the waveform strip, however many buckets the JSON carries. */
const MAX_BARS = 200;

/** Keyboard nudge for the range handles. */
const NUDGE_MS = 1_000;

const STATUS_LABEL: Record<ClipStatus, string> = {
  queued: "في قائمة الانتظار…",
  rendering: "جارٍ إنشاء المقطع…",
  done: "المقطع جاهز",
  failed: "تعذّر إنشاء المقطع",
};

const THROTTLED = "وصلنا عدد كبير من طلباتك — جرّب مرة أخرى بعد ساعة، مع الشكر";
const GENERIC = "تعذّر إنشاء المقطع الآن. حاول مرة أخرى بعد قليل.";

/** Peak buckets reduced to at most MAX_BARS, keeping the loudest of each group. */
function toBars(peaks: number[]): number[] {
  if (peaks.length <= MAX_BARS) return peaks;
  const groupSize = peaks.length / MAX_BARS;
  const bars: number[] = [];
  for (let bar = 0; bar < MAX_BARS; bar += 1) {
    const from = Math.floor(bar * groupSize);
    const to = Math.min(peaks.length, Math.floor((bar + 1) * groupSize));
    let loudest = 0;
    for (let i = from; i < to; i += 1) loudest = Math.max(loudest, peaks[i]);
    bars.push(loudest);
  }
  return bars;
}

/** Live playhead of this segment, or 0 when something else is loaded. */
function playheadMs(segmentId: number): number {
  const { current, positionMs, _el } = useAudioStore.getState();
  if (current === null || current.segmentId !== segmentId) return 0;
  return _el ? Math.floor(_el.currentTime * 1000) : positionMs;
}

/**
 * "مقطع للمشاركة" — the entry point on the player screen.
 *
 * The body is mounted only while open, so closing it drops the draft range,
 * the preset and any in-flight polling without extra bookkeeping.
 */
export default function ClipComposer({ segment }: ClipComposerProps) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((previous) => !previous)}
        aria-expanded={open}
        className="rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-ink-muted)]"
      >
        {open ? "إغلاق المقطع" : "مقطع للمشاركة"}
      </button>
      {open ? (
        <ClipComposerBody segment={segment} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}

interface ClipComposerBodyProps {
  segment: Segment;
  onClose: () => void;
}

function ClipComposerBody({ segment, onClose }: ClipComposerBodyProps) {
  const durationMs = segment.duration_ms;
  const clippable = canClipSegment(durationMs);

  const [range, setRange] = useState<ClipRange>(() =>
    defaultClipRange(playheadMs(segment.id), durationMs)
  );
  const [preset, setPreset] = useState<PresetId>("classic");

  // null = still loading, [] = unavailable (falls back to two sliders).
  const [peaks, setPeaks] = useState<number[] | null>(null);

  const [clipId, setClipId] = useState<string | null>(null);
  const [clip, setClip] = useState<Clip | null>(null);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");
  const [timedOut, setTimedOut] = useState(false);

  // ---- waveform -----------------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();

    const load = async () => {
      try {
        const response = await fetch(segment.waveform_url, {
          signal: controller.signal,
        });
        if (!response.ok) throw new Error(String(response.status));
        const data = (await response.json()) as Waveform;
        if (cancelled) return;
        setPeaks(Array.isArray(data.peaks) ? data.peaks : []);
      } catch {
        if (!cancelled) setPeaks([]);
      }
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [segment.waveform_url]);

  const bars = useMemo(() => (peaks ? toBars(peaks) : []), [peaks]);

  // ---- render polling -----------------------------------------------------
  useEffect(() => {
    if (clipId === null) return;

    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      attempts += 1;
      try {
        const next = await getClip(clipId);
        if (cancelled) return;
        setClip(next);
        if (next.status === "done" || next.status === "failed") return;
      } catch {
        if (cancelled) return;
      }
      if (attempts >= MAX_POLLS) {
        setTimedOut(true);
        return;
      }
      timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };

    timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [clipId]);

  // ---- dragging -----------------------------------------------------------
  const trackRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef<"start" | "end" | null>(null);

  // The strip is a time axis, so it stays left-to-right inside the RTL page.
  const msFromClientX = useCallback(
    (clientX: number): number => {
      const element = trackRef.current;
      if (element === null) return 0;
      const rect = element.getBoundingClientRect();
      if (rect.width === 0) return 0;
      const ratio = (clientX - rect.left) / rect.width;
      return Math.round(Math.min(Math.max(ratio, 0), 1) * durationMs);
    },
    [durationMs]
  );

  const moveHandle = useCallback(
    (handle: "start" | "end", ms: number) => {
      setRange((previous) =>
        handle === "start"
          ? moveClipStart(previous, ms, durationMs)
          : moveClipEnd(previous, ms, durationMs)
      );
    },
    [durationMs]
  );

  const handleProps = (handle: "start" | "end") => ({
    onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => {
      event.preventDefault();
      draggingRef.current = handle;
      event.currentTarget.setPointerCapture(event.pointerId);
    },
    onPointerMove: (event: React.PointerEvent<HTMLButtonElement>) => {
      if (draggingRef.current !== handle) return;
      moveHandle(handle, msFromClientX(event.clientX));
    },
    onPointerUp: (event: React.PointerEvent<HTMLButtonElement>) => {
      draggingRef.current = null;
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
    },
    onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => {
      const at = handle === "start" ? range.startMs : range.endMs;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        moveHandle(handle, at - NUDGE_MS);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        moveHandle(handle, at + NUDGE_MS);
      }
    },
  });

  // ---- submit -------------------------------------------------------------
  const spanMs = range.endMs - range.startMs;

  const submit = async () => {
    setCreating(true);
    setMessage("");
    setTimedOut(false);
    try {
      const created = await createClip({
        segment_id: segment.id,
        start_ms: range.startMs,
        end_ms: range.endMs,
        preset,
      });
      setClip({ id: created.id, status: created.status, video_url: null });
      setClipId(created.id);
    } catch (error) {
      setMessage(
        error instanceof ApiError && error.status === 429 ? THROTTLED : GENERIC
      );
    } finally {
      setCreating(false);
    }
  };

  const percent = (ms: number) =>
    durationMs === 0 ? 0 : (ms / durationMs) * 100;
  const startPercent = percent(range.startMs);
  const endPercent = percent(range.endMs);

  const startBar = Math.floor((startPercent / 100) * bars.length);
  const endBar = Math.ceil((endPercent / 100) * bars.length) - 1;

  return (
    <section
      aria-label="إنشاء مقطع للمشاركة"
      className="mt-4 basis-full border-t border-[var(--color-border)] pt-4"
    >
      {!clippable ? (
        <p className="text-sm text-[var(--color-ink-muted)]">
          هذا المقطع أقصر من {MIN_CLIP_MS / 1000} ثانية، ولا يمكن اقتطاع مقطع
          منه.
        </p>
      ) : (
        <>
          {/* ---- range picker ------------------------------------------- */}
          {peaks === null ? (
            <p className="text-xs text-[var(--color-ink-faint)]">
              جارٍ تحميل الموجة الصوتية…
            </p>
          ) : bars.length > 0 ? (
            <div
              ref={trackRef}
              dir="ltr"
              className="relative h-16 w-full touch-none select-none border border-[var(--color-border)]"
            >
              <svg
                viewBox={`0 0 ${bars.length} 100`}
                preserveAspectRatio="none"
                className="h-full w-full"
                aria-hidden="true"
              >
                {bars.map((peak, index) => {
                  const height = Math.max(2, peak * 100);
                  const inside = index >= startBar && index <= endBar;
                  return (
                    <rect
                      key={index}
                      x={index + 0.15}
                      y={(100 - height) / 2}
                      width={0.7}
                      height={height}
                      fill={
                        inside
                          ? "var(--color-ink)"
                          : "var(--color-ink-faint)"
                      }
                    />
                  );
                })}
              </svg>

              {(["start", "end"] as const).map((handle) => {
                const at = handle === "start" ? range.startMs : range.endMs;
                return (
                  <button
                    key={handle}
                    type="button"
                    role="slider"
                    aria-label={
                      handle === "start" ? "بداية المقطع" : "نهاية المقطع"
                    }
                    aria-valuemin={0}
                    aria-valuemax={durationMs}
                    aria-valuenow={at}
                    aria-valuetext={formatMs(at)}
                    className="absolute inset-y-0 w-6 -translate-x-1/2 cursor-ew-resize touch-none bg-transparent"
                    style={{ left: `${percent(at)}%` }}
                    {...handleProps(handle)}
                  >
                    <span className="pointer-events-none mx-auto block h-full w-0.5 bg-[var(--color-ink)]" />
                  </button>
                );
              })}
            </div>
          ) : (
            <div dir="ltr" className="space-y-2">
              <input
                type="range"
                min={0}
                max={Math.max(1, durationMs)}
                step={500}
                value={range.startMs}
                onChange={(event) =>
                  moveHandle("start", Number(event.target.value))
                }
                aria-label="بداية المقطع"
                className="w-full accent-[var(--color-accent)]"
              />
              <input
                type="range"
                min={0}
                max={Math.max(1, durationMs)}
                step={500}
                value={range.endMs}
                onChange={(event) =>
                  moveHandle("end", Number(event.target.value))
                }
                aria-label="نهاية المقطع"
                className="w-full accent-[var(--color-accent)]"
              />
            </div>
          )}

          <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
            <span dir="ltr" className="tabular-nums">
              {formatMs(range.startMs)} – {formatMs(range.endMs)}
            </span>{" "}
            · المدة {Math.round(spanMs / 1000)} ثانية · المسموح بين{" "}
            {MIN_CLIP_MS / 1000} و {MAX_CLIP_MS / 1000} ثانية
          </p>

          {/* ---- presets ------------------------------------------------- */}
          <fieldset className="mt-4">
            <legend className="text-xs text-[var(--color-ink-faint)]">
              الشكل
            </legend>
            <div className="mt-2 flex flex-wrap gap-3">
              {PRESETS.map((option) => {
                const selected = option.id === preset;
                return (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => setPreset(option.id)}
                    aria-pressed={selected}
                    className="flex items-center gap-2 border px-2 py-1.5 text-xs"
                    style={{
                      borderColor: selected
                        ? "var(--color-ink)"
                        : "var(--color-border)",
                      color: selected
                        ? "var(--color-ink)"
                        : "var(--color-ink-muted)",
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="flex h-6 w-4 flex-col justify-end gap-0.5 p-0.5"
                      style={{ backgroundColor: option.bg }}
                    >
                      <span
                        className="block h-0.5 w-full"
                        style={{ backgroundColor: option.ink }}
                      />
                      <span
                        className="block h-0.5 w-2/3"
                        style={{ backgroundColor: option.ink }}
                      />
                    </span>
                    {option.label}
                  </button>
                );
              })}
            </div>
          </fieldset>

          {/* ---- submit + status ---------------------------------------- */}
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void submit()}
              disabled={creating || clipId !== null}
              className="rounded border border-[var(--color-border)] px-3 py-1.5 text-sm text-[var(--color-ink)] disabled:opacity-50"
            >
              {creating ? "جارٍ الإرسال…" : "إنشاء المقطع"}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="text-sm text-[var(--color-ink-muted)]"
            >
              إلغاء
            </button>
            {message !== "" ? (
              <span role="status" className="text-xs text-[var(--color-ink-muted)]">
                {message}
              </span>
            ) : null}
          </div>

          {clip !== null ? (
            <div className="mt-3 space-y-2 text-sm">
              <p role="status" className="text-[var(--color-ink-muted)]">
                {timedOut && clip.status !== "done"
                  ? "ما زال الإنشاء جاريًا — افتح صفحة المقطع بعد قليل."
                  : STATUS_LABEL[clip.status]}
              </p>
              {clip.status === "done" || timedOut ? (
                <p className="flex flex-wrap items-center gap-4">
                  <Link
                    href={`/clip/${clip.id}?segment=${segment.id}`}
                    className="text-[var(--color-ink)] underline underline-offset-4"
                  >
                    صفحة المقطع
                  </Link>
                  {clip.video_url !== null ? (
                    <a
                      href={clip.video_url}
                      download
                      className="text-[var(--color-ink-muted)] underline underline-offset-4"
                    >
                      تنزيل الفيديو
                    </a>
                  ) : null}
                </p>
              ) : null}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
