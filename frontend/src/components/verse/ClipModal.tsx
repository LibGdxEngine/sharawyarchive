"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { MIN_CLIP_MS } from "@/lib/clip-range";
import type { WordRange } from "@/lib/correction-selection";
import { formatMs } from "@/lib/format";
import { SITE_URL } from "@/lib/site";
import {
  isTrimLegal,
  moveTrimEnd,
  moveTrimStart,
  trimFromRange,
  trimTimesMs,
} from "@/lib/word-trim";
import type { WordTrim } from "@/lib/word-trim";
import { useActiveWordIndex } from "@/components/player/useActiveWord";
import { useClipRender } from "@/components/player/useClipRender";
import { useRangePlayback } from "./useRangePlayback";
import ClipPreview, { CLIP_THEMES, CLIP_THEME_PRESET } from "./ClipPreview";
import type { ClipTheme } from "./ClipPreview";
import type { ClipStatus, Segment, TranscriptWord } from "@/types/models";

/** Words shown around the trim for context, each side. */
const CONTEXT_WORDS = 8;

const STATUS_LABEL: Record<ClipStatus, string> = {
  queued: "في قائمة الانتظار…",
  rendering: "جارٍ إنشاء المقطع…",
  done: "المقطع جاهز",
  failed: "تعذّر إنشاء المقطع",
};

interface ClipModalProps {
  segment: Segment;
  words: TranscriptWord[];
  /** Transcript positions inside a located ayah recitation. */
  isQuranWord(index: number): boolean;
  /** The word selection that opened the modal. */
  initialRange: WordRange;
  onClose(): void;
}

/**
 * "إنشاء مقطع للمشاركة" — the verse page's clip dialog (mockup): the trim
 * follows WORDS, not the waveform; a 9:16 themed preview mirrors the render;
 * the server does the actual MP4 via the existing clips API.
 */
export default function ClipModal({
  segment,
  words,
  isQuranWord,
  initialRange,
  onClose,
}: ClipModalProps) {
  const [trim, setTrim] = useState<WordTrim>(() =>
    trimFromRange(words, initialRange)
  );
  const [theme, setTheme] = useState<ClipTheme>(CLIP_THEMES[0]);
  const [shareNote, setShareNote] = useState("");
  const render = useClipRender();
  const { activeRange, playRange, stop } = useRangePlayback(segment.id);
  const activeWordIndex = useActiveWordIndex(segment.id, words);

  const { startMs, endMs } = trimTimesMs(words, trim);
  const spanMs = endMs - startMs;
  const legal = isTrimLegal(words, trim);

  // ---- dialog plumbing: Escape, focus trap, initial focus ------------------
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (!dialog) return;
      const focusable = dialog.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  // ---- word-snapped handle dragging ----------------------------------------
  // State rather than a ref: the handlers below are created during render,
  // and mutating a ref there is what the compiler rules forbid.
  const [dragging, setDragging] = useState<"start" | "end" | null>(null);

  const wordIndexAt = (clientX: number, clientY: number): number | null => {
    const element = document.elementFromPoint(clientX, clientY);
    const wordEl = element?.closest<HTMLElement>("[data-trim-index]");
    if (!wordEl) return null;
    const index = Number.parseInt(wordEl.dataset.trimIndex ?? "", 10);
    return Number.isInteger(index) ? index : null;
  };

  const moveHandle = useCallback(
    (handle: "start" | "end", targetWord: number) => {
      setTrim((previous) =>
        handle === "start"
          ? moveTrimStart(words, previous, targetWord)
          : moveTrimEnd(words, previous, targetWord)
      );
    },
    [words]
  );

  const handleProps = (handle: "start" | "end") => {
    const at = handle === "start" ? trim.startWord : trim.endWord;
    return {
      onPointerDown: (event: React.PointerEvent<HTMLButtonElement>) => {
        event.preventDefault();
        setDragging(handle);
        event.currentTarget.setPointerCapture(event.pointerId);
      },
      onPointerMove: (event: React.PointerEvent<HTMLButtonElement>) => {
        if (dragging !== handle) return;
        const index = wordIndexAt(event.clientX, event.clientY);
        if (index !== null) moveHandle(handle, index);
      },
      onPointerUp: (event: React.PointerEvent<HTMLButtonElement>) => {
        setDragging(null);
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
      },
      onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => {
        // RTL text: visually-right (ArrowRight) is one word EARLIER.
        if (event.key === "ArrowRight") {
          event.preventDefault();
          moveHandle(handle, at - 1);
        } else if (event.key === "ArrowLeft") {
          event.preventDefault();
          moveHandle(handle, at + 1);
        }
      },
    };
  };

  // ---- render + share -------------------------------------------------------
  const clipUrl =
    render.clip !== null
      ? `${SITE_URL}/clip/${render.clip.id}?segment=${segment.id}`
      : null;
  const shareText = clipUrl !== null ? `${segment.title} — ${clipUrl}` : "";

  const onInstagram = (): void => {
    if (clipUrl === null) return;
    if (typeof navigator.share === "function") {
      void navigator
        .share({ title: segment.title, url: clipUrl })
        .catch(() => undefined);
      return;
    }
    setShareNote("نزّل الفيديو ثم شاركه من تطبيق إنستغرام.");
  };

  const contextStart = Math.max(0, trim.startWord - CONTEXT_WORDS);
  const contextEnd = Math.min(words.length - 1, trim.endWord + CONTEXT_WORDS);
  const strip: React.ReactNode[] = [];
  for (let index = contextStart; index <= contextEnd; index += 1) {
    if (index === trim.startWord) {
      strip.push(
        <button
          key="handle-start"
          type="button"
          role="slider"
          dir="ltr"
          aria-label="بداية المقطع"
          aria-valuemin={0}
          aria-valuemax={words.length - 1}
          aria-valuenow={trim.startWord}
          aria-valuetext={`${words[trim.startWord].t} · ${formatMs(startMs)}`}
          className="mx-1 inline-block cursor-ew-resize touch-none rounded-md bg-[var(--verse-gold)] px-1.5 py-0.5 text-[15px] font-extrabold text-[var(--verse-gold-ink)]"
          {...handleProps("start")}
        >
          ]
        </button>
      );
    }
    const inTrim = index >= trim.startWord && index <= trim.endWord;
    strip.push(
      <span key={index}>
        <span
          data-trim-index={index}
          className={`rounded px-0.5 ${
            inTrim
              ? "verse-word-selected text-[var(--color-ink)]"
              : "text-[var(--color-ink-faint)]"
          }`}
        >
          {words[index].t}
        </span>{" "}
      </span>
    );
    if (index === trim.endWord) {
      strip.push(
        <button
          key="handle-end"
          type="button"
          role="slider"
          dir="ltr"
          aria-label="نهاية المقطع"
          aria-valuemin={0}
          aria-valuemax={words.length - 1}
          aria-valuenow={trim.endWord}
          aria-valuetext={`${words[trim.endWord].t} · ${formatMs(endMs)}`}
          className="mx-1 inline-block cursor-ew-resize touch-none rounded-md bg-[var(--verse-gold)] px-1.5 py-0.5 text-[15px] font-extrabold text-[var(--verse-gold-ink)]"
          {...handleProps("end")}
        >
          [
        </button>
      );
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(30,24,12,0.55)] p-4 sm:p-6"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="إنشاء مقطع للمشاركة"
        onClick={(event) => event.stopPropagation()}
        className="max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-2xl bg-[var(--color-surface)] p-6 shadow-[0_40px_90px_rgba(20,16,8,0.4)] sm:p-7"
      >
        <div className="flex items-center gap-3">
          <h2 className="text-xl font-bold [font-family:var(--font-amiri)]">
            إنشاء مقطع للمشاركة
          </h2>
          <span className="rounded-full bg-[var(--verse-badge-bg)] px-2.5 py-0.5 text-xs font-semibold text-[var(--verse-deep)]">
            {Math.round(spanMs / 1000)} ثانية
          </span>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="إغلاق"
            className="ms-auto px-2 py-1 text-xl leading-none text-[var(--color-ink-faint)] hover:text-[var(--color-ink)]"
          >
            ×
          </button>
        </div>

        <div className="mt-5 flex flex-wrap gap-6">
          <div className="mx-auto shrink-0">
            <ClipPreview
              words={words}
              trim={trim}
              theme={theme}
              isQuranWord={isQuranWord}
              activeWordIndex={activeWordIndex}
            />
            <button
              type="button"
              onClick={() =>
                activeRange !== null ? stop() : playRange({ startMs, endMs })
              }
              className="mt-2 w-full rounded border border-[var(--color-border)] px-3 py-1.5 text-xs text-[var(--color-ink-muted)] hover:border-[var(--verse-gold)]"
            >
              {activeRange !== null ? "إيقاف المعاينة" : "معاينة الصوت"}
            </button>
          </div>

          <div className="min-w-[280px] flex-1">
            <p className="text-sm font-semibold text-[var(--color-ink-muted)]">
              اضبط الحدود بسحب القوسين — القصّ يتبع الكلمات، لا الموجة الصوتية
            </p>
            <p className="mt-3 select-none rounded-xl border border-[var(--color-border)] bg-[var(--color-bg-subtle)] p-4 text-base leading-[2.3]">
              {strip}
            </p>
            <p className="mt-2 text-xs text-[var(--color-ink-muted)]">
              <span dir="ltr" className="tabular-nums">
                {formatMs(startMs)} – {formatMs(endMs)}
              </span>{" "}
              · الحد الأدنى {MIN_CLIP_MS / 1000} ثانية وحتى نهاية المقطع
            </p>
            {!legal ? (
              <p role="status" className="mt-1 text-xs text-[var(--verse-deep)]">
                المدة خارج الحدود المسموحة — حرّك القوسين لتقصير المقطع أو
                إطالته.
              </p>
            ) : null}

            <fieldset className="mt-5">
              <legend className="text-sm font-semibold text-[var(--color-ink-muted)]">
                النمط
              </legend>
              <div className="mt-2.5 flex flex-wrap gap-3">
                {CLIP_THEMES.map((option) => {
                  const selected = option.id === theme.id;
                  return (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => setTheme(option)}
                      aria-pressed={selected}
                      className="flex items-center gap-2 rounded-[10px] border-[1.5px] px-3.5 py-2 text-[13px]"
                      style={{
                        borderColor: selected
                          ? "var(--verse-gold)"
                          : "var(--color-border)",
                      }}
                    >
                      <span
                        aria-hidden="true"
                        className="flex h-6 w-6 items-center justify-center rounded-md text-xs [font-family:var(--font-amiri)]"
                        style={{
                          background: option.swatchBg,
                          color: option.swatchInk,
                        }}
                      >
                        ش
                      </span>
                      {option.label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-2 text-xs text-[var(--color-ink-faint)]">
                تُعرض كلمات الآيات دائمًا بالخطّ القرآني وبلونٍ مميّز، مهما كان
                النمط. يُنشأ الفيديو بأقرب شكلٍ معتمد في الأرشيف لهذا النمط.
              </p>
            </fieldset>

            <div className="mt-6 flex flex-wrap items-center gap-2.5">
              <button
                type="button"
                onClick={() =>
                  render.submit({
                    segment_id: segment.id,
                    start_ms: startMs,
                    end_ms: endMs,
                    preset: CLIP_THEME_PRESET[theme.id],
                  })
                }
                disabled={!legal || render.creating || render.submitted}
                className="rounded-lg bg-[var(--verse-gold)] px-6 py-2.5 text-sm font-bold text-[var(--verse-gold-ink)] hover:bg-[var(--verse-gold-hover)] disabled:opacity-50"
              >
                {render.creating ? "جارٍ الإرسال…" : "إنشاء الفيديو"}
              </button>
              {render.clip !== null ? (
                <span role="status" className="text-xs text-[var(--color-ink-muted)]">
                  {render.timedOut && render.clip.status !== "done"
                    ? "ما زال الإنشاء جاريًا — افتح صفحة المقطع بعد قليل."
                    : STATUS_LABEL[render.clip.status]}
                </span>
              ) : null}
              {render.message !== "" ? (
                <span role="status" className="text-xs text-[var(--color-ink-muted)]">
                  {render.message}
                </span>
              ) : null}
            </div>

            {render.clip !== null &&
            (render.clip.status === "done" || render.timedOut) &&
            clipUrl !== null ? (
              <div className="mt-4 flex flex-wrap items-center gap-2.5 text-sm">
                {render.clip.video_url !== null ? (
                  <a
                    href={render.clip.video_url}
                    download
                    className="rounded-lg bg-[var(--verse-gold)] px-5 py-2.5 font-bold text-[var(--verse-gold-ink)] hover:bg-[var(--verse-gold-hover)]"
                  >
                    تنزيل الفيديو MP4
                  </a>
                ) : null}
                <a
                  href={`https://wa.me/?text=${encodeURIComponent(shareText)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg border border-[var(--color-border)] px-4 py-2.5 text-[var(--color-ink-muted)] hover:border-[var(--verse-gold)]"
                >
                  واتساب
                </a>
                <a
                  href={`https://x.com/intent/post?text=${encodeURIComponent(
                    segment.title
                  )}&url=${encodeURIComponent(clipUrl)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="rounded-lg border border-[var(--color-border)] px-4 py-2.5 text-[var(--color-ink-muted)] hover:border-[var(--verse-gold)]"
                >
                  X
                </a>
                <button
                  type="button"
                  onClick={onInstagram}
                  className="rounded-lg border border-[var(--color-border)] px-4 py-2.5 text-[var(--color-ink-muted)] hover:border-[var(--verse-gold)]"
                >
                  إنستغرام
                </button>
                <Link
                  href={`/clip/${render.clip.id}?segment=${segment.id}`}
                  className="text-[var(--color-ink)] underline underline-offset-4"
                >
                  صفحة المقطع
                </Link>
              </div>
            ) : null}
            {shareNote !== "" ? (
              <p role="status" className="mt-2 text-xs text-[var(--color-ink-muted)]">
                {shareNote}
              </p>
            ) : null}

            <p className="mt-4 text-xs text-[var(--color-ink-faint)]">
              تُضاف علامة الأرشيف ورابط المقطع تلقائيًا إلى كلّ فيديو.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
