"use client";

import { Fragment, useEffect, useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { buildLines, buildWordLineMap } from "@/lib/transcript";
import type { WordTrim } from "@/lib/word-trim";
import TrimHandle from "./TrimHandle";
import { useTrimHandles } from "./useTrimHandles";
import type { TranscriptWord } from "@/types/models";

interface ClipWordPickerProps {
  words: TranscriptWord[];
  trim: WordTrim;
  setTrim(next: (previous: WordTrim) => WordTrim): void;
  /** Word being spoken right now, or -1. */
  activeWordIndex: number;
  /**
   * Word to bring into view. Changing it scrolls; it is a `{ index }` box
   * rather than a bare number so that asking twice for the same word (scrub
   * back to where you were) still scrolls.
   */
  scrollTo: { index: number } | null;
}

/**
 * "اختر الكلمات" — pick the clip's start and end by pointing at what was said.
 *
 * This is the answer to a picker that could not express a short selection in a
 * long segment: segment 10 is 84 minutes against 800 waveform buckets, so both
 * handles of the old time slider landed on the same pixel. Words are the
 * natural unit here anyway — a clip is a sentence, not an interval — and there
 * are 8,986 of them, so the list is virtualized by pause-aware line the way the
 * /listen transcript pane is.
 */
export default function ClipWordPicker({
  words,
  trim,
  setTrim,
  activeWordIndex,
  scrollTo,
}: ClipWordPickerProps) {
  const lines = useMemo(() => buildLines(words), [words]);
  const wordToLine = useMemo(
    () => buildWordLineMap(lines, words.length),
    [lines, words.length]
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const { dragging, moveHandle, handleProps } = useTrimHandles(words, setTrim);

  // Virtualizing is a hard requirement at this size, and this hook opts the
  // component out of React Compiler memoization — harmless here.
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer<HTMLDivElement, HTMLDivElement>({
    count: lines.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 44,
    overscan: 6,
  });

  const scrollToLine = virtualizer.scrollToIndex;
  useEffect(() => {
    if (scrollTo === null) return;
    const index = wordToLine[Math.min(scrollTo.index, wordToLine.length - 1)];
    if (index !== undefined) scrollToLine(index, { align: "center" });
  }, [scrollTo, wordToLine, scrollToLine]);

  /** Tapping a word moves whichever handle is nearer — never both. */
  const tapWord = (index: number): void => {
    const toStart = Math.abs(index - trim.startWord);
    const toEnd = Math.abs(index - trim.endWord);
    moveHandle(toStart <= toEnd ? "start" : "end", index);
  };

  return (
    <div
      ref={scrollRef}
      className="mt-3 h-72 overflow-y-auto overscroll-contain rounded border border-[var(--lp-card-border)] bg-[var(--color-bg-subtle)] p-3"
    >
      <div
        className="relative w-full"
        style={{ height: `${virtualizer.getTotalSize()}px` }}
      >
        {virtualizer.getVirtualItems().map((row) => {
          const line = lines[row.index];
          return (
            <div
              key={row.key}
              ref={virtualizer.measureElement}
              data-index={row.index}
              className="absolute inset-x-0 top-0 py-1 text-base leading-[2.1]"
              style={{ transform: `translateY(${row.start}px)` }}
            >
              {line.words.map((word, offset) => {
                const index = line.startIndex + offset;
                const inTrim =
                  index >= trim.startWord && index <= trim.endWord;
                return (
                  <Fragment key={word.i}>
                    {index === trim.startWord ? (
                      <TrimHandle
                        handle="start"
                        words={words}
                        at={trim.startWord}
                        opposite={trim.endWord}
                        dragging={dragging === "start"}
                        pointer={handleProps("start", trim.startWord)}
                      />
                    ) : null}
                    <span
                      data-trim-index={index}
                      role="button"
                      tabIndex={-1}
                      onClick={() => tapWord(index)}
                      className={`cursor-pointer rounded px-0.5 ${
                        inTrim
                          ? "bg-[var(--color-accent-bg)] text-[var(--color-ink)]"
                          : "text-[var(--color-ink-faint)] hover:text-[var(--color-ink-muted)]"
                      } ${
                        index === activeWordIndex
                          ? "underline decoration-[var(--color-accent)] decoration-2 underline-offset-4"
                          : ""
                      }`}
                    >
                      {word.t}
                    </span>
                    {index === trim.endWord ? (
                      <TrimHandle
                        handle="end"
                        words={words}
                        at={trim.endWord}
                        opposite={trim.startWord}
                        dragging={dragging === "end"}
                        pointer={handleProps("end", trim.endWord)}
                      />
                    ) : null}{" "}
                  </Fragment>
                );
              })}
            </div>
          );
        })}
      </div>
    </div>
  );
}
