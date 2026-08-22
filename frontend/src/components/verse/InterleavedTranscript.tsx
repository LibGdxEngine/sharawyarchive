"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useWindowVirtualizer } from "@tanstack/react-virtual";
import { useAudioStore } from "@/lib/audio-store";
import type { AyahRef, AyahTokenAlignment, VerseBlock } from "@/lib/ayah-match";
import { canClipSegment } from "@/lib/clip-range";
import type { WordRange } from "@/lib/correction-selection";
import { LINE_BREAK_GAP_MS } from "@/lib/transcript";
import {
  IDLE_DRAG,
  beginDrag,
  dragRange,
  endDrag,
  extendDrag,
  isMultiWord,
  rangeTimesMs,
} from "@/lib/verse-selection";
import type { DragState } from "@/lib/verse-selection";
import {
  useActiveWordIndex,
  usePrefersReducedMotion,
} from "@/components/player/useActiveWord";
import AyahCard from "./AyahCard";
import ClipModal from "./ClipModal";
import SelectionToolbar from "./SelectionToolbar";
import { useRangePlayback } from "./useRangePlayback";
import type { Segment, TranscriptWord } from "@/types/models";

/** Tafseer paragraphs break on the Sheikh's pauses, capped for virtualization. */
const PARAGRAPH_MAX_WORDS = 60;

/** Where in the viewport the active row should sit while following. */
const ACTIVE_ROW_VIEWPORT_RATIO = 0.4;

/** Touch: a hold this long on a word starts selecting instead of scrolling. */
const LONG_PRESS_MS = 400;

/** Touch movement past this many px before the hold fires means "scroll". */
const LONG_PRESS_SLOP_PX = 8;

/** Pointer-drag near the viewport edge nudges the window along. */
const EDGE_SCROLL_ZONE_PX = 96;
const EDGE_SCROLL_STEP_PX = 14;

type Row =
  | { type: "ayah"; ayah: AyahRef; match: AyahTokenAlignment | null }
  | { type: "taf"; start: number; end: number };

function buildRows(blocks: VerseBlock[], words: TranscriptWord[]): Row[] {
  const rows: Row[] = [];
  for (const block of blocks) {
    if (block.kind === "ayah") {
      rows.push({ type: "ayah", ayah: block.ayah, match: block.match });
      continue;
    }
    // Split a tafseer run into paragraphs at long silences / the word cap.
    let start = block.wordStart;
    for (let i = block.wordStart + 1; i <= block.wordEnd; i += 1) {
      const gap = words[i].s - words[i - 1].e;
      if (i - start >= PARAGRAPH_MAX_WORDS || gap > LINE_BREAK_GAP_MS) {
        rows.push({ type: "taf", start, end: i - 1 });
        start = i;
      }
    }
    rows.push({ type: "taf", start, end: block.wordEnd });
  }
  return rows;
}

function wordIndexAt(clientX: number, clientY: number): number | null {
  const element = document.elementFromPoint(clientX, clientY);
  const wordEl = element?.closest<HTMLElement>("[data-word-index]");
  if (!wordEl) return null;
  const index = Number.parseInt(wordEl.dataset.wordIndex ?? "", 10);
  return Number.isInteger(index) ? index : null;
}

interface InterleavedTranscriptProps {
  segment: Segment;
  words: TranscriptWord[];
  blocks: VerseBlock[];
  surahName: string | null;
}

/**
 * The article of the verse page: verified ayah cards interleaved with the
 * machine transcript, word-synced to playback, with drag-selection actions
 * (play / clip / moment link) — the "Sharawy Player" mockup made real.
 *
 * Rows are window-virtualized: a 90-minute episode is thousands of words, and
 * only the paragraphs near the viewport should exist in the DOM.
 */
export default function InterleavedTranscript({
  segment,
  words,
  blocks,
  surahName,
}: InterleavedTranscriptProps) {
  const seekMs = useAudioStore((s) => s.seekMs);
  const reducedMotion = usePrefersReducedMotion();
  const { playRange } = useRangePlayback(segment.id);

  const rows = useMemo(() => buildRows(blocks, words), [blocks, words]);

  const wordToRow = useMemo(() => {
    const map = new Int32Array(words.length).fill(-1);
    rows.forEach((row, rowIndex) => {
      if (row.type === "taf") {
        for (let i = row.start; i <= row.end; i += 1) map[i] = rowIndex;
      } else if (row.match !== null) {
        for (let i = row.match.wordStart; i <= row.match.wordEnd; i += 1) {
          map[i] = rowIndex;
        }
      }
    });
    return map;
  }, [rows, words.length]);

  // Transcript positions that belong to a located recitation — these render
  // as ayah cards here, and keep the Quran face inside the clip preview.
  const quranWords = useMemo(() => {
    const set = new Set<number>();
    for (const row of rows) {
      if (row.type === "ayah" && row.match !== null) {
        for (let i = row.match.wordStart; i <= row.match.wordEnd; i += 1) {
          set.add(i);
        }
      }
    }
    return set;
  }, [rows]);
  const isQuranWord = useCallback(
    (index: number) => quranWords.has(index),
    [quranWords]
  );

  const activeWordIndex = useActiveWordIndex(segment.id, words);
  const activeRow =
    activeWordIndex >= 0 && activeWordIndex < wordToRow.length
      ? wordToRow[activeWordIndex]
      : -1;

  // ---- selection state ------------------------------------------------------
  const [selection, setSelection] = useState<DragState>(IDLE_DRAG);
  // Mirror of the committed selection for event handlers. Written in an
  // effect (commit phase), never during render.
  const selectionRef = useRef(selection);
  useEffect(() => {
    selectionRef.current = selection;
  }, [selection]);
  const [toolbar, setToolbar] = useState<{ x: number; y: number } | null>(null);
  const [clipRange, setClipRange] = useState<WordRange | null>(null);
  const [toast, setToast] = useState("");
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const range = dragRange(selection);

  const showToast = useCallback((message: string) => {
    setToast(message);
    clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(""), 2200);
  }, []);
  useEffect(() => () => clearTimeout(toastTimer.current), []);

  const clearSelection = useCallback(() => {
    setSelection(IDLE_DRAG);
    setToolbar(null);
  }, []);

  // ---- pointer drag-selection ------------------------------------------------
  const containerRef = useRef<HTMLElement>(null);
  const pendingRef = useRef<{
    index: number;
    x: number;
    y: number;
    pointerId: number;
    pointerType: string;
  } | null>(null);
  const longPressTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined
  );
  const suppressClickRef = useRef(false);

  const startDrag = useCallback((index: number, pointerId: number) => {
    setSelection(beginDrag(index));
    setToolbar(null);
    try {
      containerRef.current?.setPointerCapture(pointerId);
    } catch {
      // Capture is an optimization; selection works without it.
    }
  }, []);

  const placeToolbar = useCallback((state: DragState, fallback: { x: number; y: number }) => {
    const focusEl =
      state.focus !== null
        ? document.querySelector<HTMLElement>(`[data-word-index="${state.focus}"]`)
        : null;
    const rect = focusEl?.getBoundingClientRect();
    const x = Math.min(
      Math.max(rect ? rect.left + rect.width / 2 : fallback.x, 110),
      window.innerWidth - 110
    );
    const y = Math.max(rect ? rect.top - 10 : fallback.y - 10, 70);
    setToolbar({ x, y });
  }, []);

  const onPointerDown = (event: React.PointerEvent<HTMLElement>) => {
    if (event.button !== 0 && event.pointerType === "mouse") return;
    const index = wordIndexAt(event.clientX, event.clientY);
    if (index === null) {
      clearSelection();
      return;
    }
    pendingRef.current = {
      index,
      x: event.clientX,
      y: event.clientY,
      pointerId: event.pointerId,
      pointerType: event.pointerType,
    };
    if (event.pointerType === "touch") {
      clearTimeout(longPressTimer.current);
      longPressTimer.current = setTimeout(() => {
        const pending = pendingRef.current;
        if (pending !== null) startDrag(pending.index, pending.pointerId);
      }, LONG_PRESS_MS);
    }
  };

  const onPointerMove = (event: React.PointerEvent<HTMLElement>) => {
    const state = selectionRef.current;
    if (state.dragging) {
      // Nudge the window when the drag reaches the viewport edges.
      if (event.clientY < EDGE_SCROLL_ZONE_PX) {
        window.scrollBy(0, -EDGE_SCROLL_STEP_PX);
      } else if (event.clientY > window.innerHeight - EDGE_SCROLL_ZONE_PX) {
        window.scrollBy(0, EDGE_SCROLL_STEP_PX);
      }
      const index = wordIndexAt(event.clientX, event.clientY);
      if (index !== null) setSelection((prev) => extendDrag(prev, index));
      return;
    }

    const pending = pendingRef.current;
    if (pending === null) return;
    const moved = Math.hypot(event.clientX - pending.x, event.clientY - pending.y);
    if (pending.pointerType === "touch") {
      // Movement before the hold fires means the reader is scrolling.
      if (moved > LONG_PRESS_SLOP_PX) {
        clearTimeout(longPressTimer.current);
        pendingRef.current = null;
      }
      return;
    }
    const index = wordIndexAt(event.clientX, event.clientY);
    if (index !== null && index !== pending.index) {
      startDrag(pending.index, pending.pointerId);
      setSelection((prev) => extendDrag(prev, index));
    }
  };

  const finishPointer = (event: React.PointerEvent<HTMLElement>) => {
    clearTimeout(longPressTimer.current);
    pendingRef.current = null;
    const state = selectionRef.current;
    if (!state.dragging) return;
    const ended = endDrag(state);
    setSelection(ended);
    suppressClickRef.current = true;
    setTimeout(() => {
      suppressClickRef.current = false;
    }, 0);
    if (isMultiWord(ended)) {
      placeToolbar(ended, { x: event.clientX, y: event.clientY });
    } else {
      clearSelection();
    }
  };

  const onPointerCancel = () => {
    clearTimeout(longPressTimer.current);
    pendingRef.current = null;
    if (selectionRef.current.dragging) clearSelection();
  };

  // While a touch drag is live, the page must not pan underneath it.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const onTouchMove = (event: TouchEvent) => {
      if (selectionRef.current.dragging) event.preventDefault();
    };
    container.addEventListener("touchmove", onTouchMove, { passive: false });
    return () => container.removeEventListener("touchmove", onTouchMove);
  }, []);

  // Escape clears the selection wherever focus is.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && clipRange === null) clearSelection();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [clearSelection, clipRange]);

  // ---- word click: seek, or shift-click range for keyboard/AT users ----------
  const onWordClick = (event: React.MouseEvent, index: number) => {
    if (suppressClickRef.current) return;
    if (event.shiftKey) {
      const state = selectionRef.current;
      const next: DragState =
        state.anchor === null || isMultiWord(state)
          ? { anchor: index, focus: index, dragging: false }
          : { anchor: state.anchor, focus: index, dragging: false };
      setSelection(next);
      placeToolbar(next, { x: event.clientX, y: event.clientY });
      return;
    }
    clearSelection();
    seekMs(words[index].s);
  };

  // ---- toolbar actions --------------------------------------------------------
  const actOnRange = (): WordRange | null => {
    const current = dragRange(selectionRef.current);
    clearSelection();
    return current;
  };

  const onPlaySelection = () => {
    const current = actOnRange();
    if (current !== null) playRange(rangeTimesMs(words, current));
  };

  const onClipSelection = () => {
    const current = actOnRange();
    if (current !== null) setClipRange(current);
  };

  const onCopyMoment = () => {
    const current = actOnRange();
    if (current === null) return;
    const { startMs } = rangeTimesMs(words, current);
    const url = new URL(window.location.href);
    url.searchParams.set("seg", String(segment.id));
    url.searchParams.set("t", String(startMs));
    void navigator.clipboard
      .writeText(url.toString())
      .then(() => showToast("نُسخ رابط اللحظة — يفتح من الثانية نفسها"))
      .catch(() => window.prompt("انسخ الرابط", url.toString()));
  };

  // ---- window virtualization ---------------------------------------------------
  // The list's offset from the window top, measured when the container mounts
  // (callback refs run at commit, so no ref is read during render).
  const [listTop, setListTop] = useState(0);
  const listRef = useCallback((node: HTMLDivElement | null) => {
    if (node !== null) setListTop(node.offsetTop);
  }, []);
  // Virtualizing thousands of words is a hard requirement — same trade-off
  // as TranscriptView.
  const virtualizer = useWindowVirtualizer({
    count: rows.length,
    estimateSize: () => 120,
    overscan: 8,
    scrollMargin: listTop,
  });

  // ---- follow the speaker --------------------------------------------------------
  const [autoScroll, setAutoScroll] = useState(true);

  const scrollToActiveRow = useCallback(
    (rowIndex: number, behavior: ScrollBehavior) => {
      if (rowIndex < 0) return;
      const offset = virtualizer.getOffsetForIndex(rowIndex, "start");
      if (!offset) return;
      const top = Math.max(
        0,
        offset[0] - window.innerHeight * ACTIVE_ROW_VIEWPORT_RATIO
      );
      window.scrollTo({ top, behavior });
    },
    [virtualizer]
  );

  useEffect(() => {
    if (!autoScroll || activeRow < 0 || clipRange !== null) return;
    if (selectionRef.current.dragging) return;
    scrollToActiveRow(activeRow, reducedMotion ? "auto" : "smooth");
  }, [activeRow, autoScroll, clipRange, reducedMotion, scrollToActiveRow]);

  // Any deliberate scroll gesture hands control back to the reader.
  useEffect(() => {
    const release = () => {
      if (!selectionRef.current.dragging) setAutoScroll(false);
    };
    window.addEventListener("wheel", release, { passive: true });
    window.addEventListener("touchmove", release, { passive: true });
    return () => {
      window.removeEventListener("wheel", release);
      window.removeEventListener("touchmove", release);
    };
  }, []);

  if (words.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-muted)]">
        لا يتوفر تفريغ نصّي لهذا المقطع.
      </p>
    );
  }

  const selectedStart = range?.start ?? -1;
  const selectedEnd = range?.end ?? -1;

  return (
    <>
      <article
        ref={containerRef}
        aria-label="نص المقطع مع الآيات الموثّقة"
        className="select-none [touch-action:pan-y]"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finishPointer}
        onPointerCancel={onPointerCancel}
      >
        <div
          ref={listRef}
          className="relative w-full"
          style={{ height: `${virtualizer.getTotalSize()}px` }}
        >
          {virtualizer.getVirtualItems().map((item) => {
            const row = rows[item.index];
            return (
              <div
                key={item.key}
                data-index={item.index}
                ref={virtualizer.measureElement}
                className="absolute top-0 w-full"
                style={{
                  insetInlineStart: 0,
                  transform: `translateY(${
                    item.start - virtualizer.options.scrollMargin
                  }px)`,
                }}
              >
                {row.type === "ayah" ? (
                  <AyahCard
                    ayah={row.ayah}
                    match={row.match}
                    activeWordIndex={activeWordIndex}
                    surahName={surahName}
                    surahNumber={segment.surah}
                    onSeekWord={(wordIndex) => {
                      if (!suppressClickRef.current) seekMs(words[wordIndex].s);
                    }}
                  />
                ) : (
                  <p className="my-4 text-[17px] leading-[2.2] text-[var(--color-ink)]">
                    {words.slice(row.start, row.end + 1).map((word, offset) => {
                      const index = row.start + offset;
                      const isActive = index === activeWordIndex;
                      const isSelected =
                        index >= selectedStart && index <= selectedEnd;
                      return (
                        <Fragment key={index}>
                          {offset > 0 ? " " : null}
                          <button
                            type="button"
                            data-transcript-word=""
                            data-word-index={index}
                            onClick={(event) => onWordClick(event, index)}
                            aria-current={isActive ? "true" : undefined}
                            className={`inline cursor-pointer bg-transparent p-0 text-inherit ${
                              isActive ? "word-active" : ""
                            } ${isSelected ? "verse-word-selected" : ""}`}
                          >
                            {word.t}
                          </button>
                        </Fragment>
                      );
                    })}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </article>

      <p aria-live="polite" className="sr-only">
        {range !== null
          ? `تم تحديد ${range.end - range.start + 1} كلمة`
          : ""}
      </p>

      {toolbar !== null && range !== null ? (
        <SelectionToolbar
          x={toolbar.x}
          y={toolbar.y}
          canClip={canClipSegment(segment.duration_ms)}
          onPlay={onPlaySelection}
          onClip={onClipSelection}
          onCopy={onCopyMoment}
        />
      ) : null}

      {!autoScroll && activeRow >= 0 ? (
        <button
          type="button"
          onClick={() => {
            setAutoScroll(true);
            scrollToActiveRow(activeRow, reducedMotion ? "auto" : "smooth");
          }}
          className="fixed bottom-[calc(var(--player-bar-height)+1.25rem)] left-1/2 z-30 -translate-x-1/2 rounded-full border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2 text-sm text-[var(--color-ink)] shadow-md"
        >
          العودة إلى الموضع الحالي
        </button>
      ) : null}

      {toast !== "" ? (
        <p
          role="status"
          className="fixed bottom-[calc(var(--player-bar-height)+1.25rem)] left-1/2 z-40 -translate-x-1/2 whitespace-nowrap rounded-full bg-[var(--verse-toolbar-bg)] px-5 py-2.5 text-sm text-[var(--verse-toolbar-ink)] shadow-[0_12px_30px_rgba(20,16,8,0.3)]"
        >
          {toast}
        </p>
      ) : null}

      {clipRange !== null ? (
        <ClipModal
          segment={segment}
          words={words}
          isQuranWord={isQuranWord}
          initialRange={clipRange}
          onClose={() => setClipRange(null)}
        />
      ) : null}
    </>
  );
}
