"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useAudioStore } from "@/lib/audio-store";
import { buildLines, buildWordLineMap } from "@/lib/transcript";
import {
  EMPTY_SELECTION,
  clearSelection,
  isWordSelected,
  rangeText,
  selectWord,
  selectedRange,
} from "@/lib/correction-selection";
import CorrectionPanel from "./CorrectionPanel";
import { useActiveWordIndex, usePrefersReducedMotion } from "./useActiveWord";
import type { TranscriptWord } from "@/types/models";

interface TranscriptViewProps {
  segmentId: number;
  words: TranscriptWord[];
}

/** Where in the scroll viewport the active line should sit. */
const ACTIVE_LINE_VIEWPORT_RATIO = 0.4;

/** Keys that mean "the reader is scrolling this pane on purpose". */
const SCROLL_KEYS = new Set([
  "ArrowUp",
  "ArrowDown",
  "PageUp",
  "PageDown",
  "Home",
  "End",
]);

/**
 * The transcript pane.
 *
 * Three loops meet here:
 *  1. useActiveWordIndex runs a rAF + binary search loop over the flat word
 *     array and yields an index only when it changes.
 *  2. buildLines groups words into pause-aware lines; @tanstack/react-virtual
 *     renders only the lines near the viewport, so a 6000-word transcript
 *     mounts ~20 rows instead of 6000 buttons.
 *  3. An effect keyed on the active LINE scrolls the pane so that line sits at
 *     40% viewport height — unless the reader has taken over scrolling.
 */
export default function TranscriptView({
  segmentId,
  words,
}: TranscriptViewProps) {
  const seekMs = useAudioStore((s) => s.seekMs);
  const reducedMotion = usePrefersReducedMotion();

  const lines = useMemo(() => buildLines(words), [words]);
  const wordToLine = useMemo(
    () => buildWordLineMap(lines, words.length),
    [lines, words.length]
  );

  const activeWordIndex = useActiveWordIndex(segmentId, words);
  const activeLineIndex =
    activeWordIndex >= 0 && activeWordIndex < wordToLine.length
      ? wordToLine[activeWordIndex]
      : -1;

  const scrollRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);

  // Correction mode: while on, clicking a word selects instead of seeking.
  const [correcting, setCorrecting] = useState(false);
  const [selection, setSelection] = useState(EMPTY_SELECTION);
  const range = selectedRange(selection);

  const leaveCorrectionMode = useCallback(() => {
    setSelection(clearSelection());
    setCorrecting(false);
  }, []);

  // Virtualizing the transcript is a hard requirement, and this hook opts the
  // component out of React Compiler memoization. Harmless here: the component
  // re-renders only at word boundaries, a few times per second.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer<HTMLDivElement, HTMLDivElement>({
    count: lines.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 48,
    overscan: 8,
  });

  const scrollActiveLineIntoPlace = useCallback(
    (lineIndex: number, behavior: ScrollBehavior) => {
      const pane = scrollRef.current;
      if (!pane || lineIndex < 0) return;
      const offset = virtualizer.getOffsetForIndex(lineIndex, "start");
      if (!offset) return;
      const top = Math.max(
        0,
        offset[0] - pane.clientHeight * ACTIVE_LINE_VIEWPORT_RATIO
      );
      // Scrolled imperatively (not via the virtualizer's own smooth-scroll
      // helper) because line heights are measured, not fixed.
      pane.scrollTo({ top, behavior });
    },
    [virtualizer]
  );

  // Follow the speaker.
  useEffect(() => {
    if (!autoScroll || activeLineIndex < 0) return;
    scrollActiveLineIntoPlace(
      activeLineIndex,
      reducedMotion ? "auto" : "smooth"
    );
  }, [activeLineIndex, autoScroll, reducedMotion, scrollActiveLineIntoPlace]);

  // Any deliberate scroll gesture hands control back to the reader.
  useEffect(() => {
    const pane = scrollRef.current;
    if (!pane) return;

    const release = () => setAutoScroll(false);
    const onKeyDown = (event: KeyboardEvent) => {
      if (SCROLL_KEYS.has(event.key)) release();
    };

    pane.addEventListener("wheel", release, { passive: true });
    pane.addEventListener("touchmove", release, { passive: true });
    pane.addEventListener("keydown", onKeyDown);
    return () => {
      pane.removeEventListener("wheel", release);
      pane.removeEventListener("touchmove", release);
      pane.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  // Escape leaves correction mode — the way out that does not need the mouse.
  useEffect(() => {
    if (!correcting) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") leaveCorrectionMode();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [correcting, leaveCorrectionMode]);

  const resumeFollowing = () => {
    setAutoScroll(true);
    scrollActiveLineIntoPlace(
      activeLineIndex,
      reducedMotion ? "auto" : "smooth"
    );
  };

  if (lines.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-muted)]">
        لا يتوفر تفريغ نصّي لهذا المقطع.
      </p>
    );
  }

  const onWordClick = (word: TranscriptWord) => {
    if (correcting) {
      setSelection((previous) => selectWord(previous, word.i));
      return;
    }
    seekMs(word.s);
  };

  return (
    <div className="relative">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          onClick={() =>
            correcting ? leaveCorrectionMode() : setCorrecting(true)
          }
          aria-pressed={correcting}
          className="text-xs text-[var(--color-ink-muted)] underline underline-offset-4"
        >
          {correcting ? "إنهاء وضع التصحيح" : "اقتراح تصحيح"}
        </button>
        {correcting ? (
          <span className="text-xs text-[var(--color-ink-faint)]">
            اختر أول كلمة ثم آخر كلمة · Esc للخروج
          </span>
        ) : null}
      </div>

      <div
        ref={scrollRef}
        tabIndex={0}
        role="group"
        aria-label="نص المقطع"
        className="h-[60vh] overflow-y-auto overflow-x-hidden"
      >
        <div
          className="relative w-full"
          style={{ height: `${virtualizer.getTotalSize()}px` }}
        >
          {virtualizer.getVirtualItems().map((virtualRow) => {
            const line = lines[virtualRow.index];
            const isActiveLine = line.index === activeLineIndex;
            return (
              <div
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={virtualizer.measureElement}
                style={{
                  position: "absolute",
                  top: 0,
                  insetInlineStart: 0,
                  width: "100%",
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <p
                  className={`py-1 text-base leading-[1.8] ${
                    isActiveLine
                      ? "text-[var(--color-ink)]"
                      : "text-[var(--color-ink-muted)]"
                  }`}
                >
                  {line.words.map((word, position) => (
                    <Fragment key={word.i}>
                      {position > 0 ? " " : null}
                      <button
                        type="button"
                        // Tells the app-wide transport that this button does
                        // not own Space or the arrows (see lib/keyboard-target).
                        data-transcript-word=""
                        onClick={() => onWordClick(word)}
                        aria-current={
                          word.i === activeWordIndex ? "true" : undefined
                        }
                        aria-pressed={
                          correcting ? isWordSelected(selection, word.i) : undefined
                        }
                        className={`inline cursor-pointer bg-transparent p-0 text-inherit ${
                          word.i === activeWordIndex ? "word-active" : ""
                        } ${
                          isWordSelected(selection, word.i) ? "word-selected" : ""
                        }`}
                      >
                        {word.t}
                      </button>
                    </Fragment>
                  ))}
                </p>
              </div>
            );
          })}
        </div>
      </div>

      {correcting && range !== null ? (
        <CorrectionPanel
          key={`${range.start}-${range.end}`}
          segmentId={segmentId}
          range={range}
          originalText={rangeText(words, range)}
          onDismiss={() => setSelection(clearSelection())}
        />
      ) : null}

      {!autoScroll && activeLineIndex >= 0 ? (
        <button
          type="button"
          onClick={resumeFollowing}
          className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2 text-sm text-[var(--color-ink)]"
        >
          العودة إلى الموضع الحالي
        </button>
      ) : null}
    </div>
  );
}
