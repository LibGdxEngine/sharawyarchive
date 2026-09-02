"use client";

import { useCallback, useState } from "react";
import { moveTrimEnd, moveTrimStart } from "@/lib/word-trim";
import type { WordTrim } from "@/lib/word-trim";
import type { TranscriptWord } from "@/types/models";

export type TrimHandleName = "start" | "end";

/** Words a Shift-arrow jumps, for crossing a long passage without 200 taps. */
const COARSE_STEP = 10;

/**
 * Drag-and-keyboard behaviour of the two trim handles, shared by the composer's
 * virtualized word list and the verse modal's context strip.
 *
 * Hit-testing goes through `document.elementFromPoint` and a `data-trim-index`
 * attribute rather than per-word pointer handlers: the handle keeps pointer
 * capture for the whole gesture (otherwise the words underneath would swallow
 * the move events), so it has to ask what is under the finger itself. That also
 * means the two callers can lay their words out however they like.
 */
export function useTrimHandles(
  words: readonly TranscriptWord[],
  setTrim: (next: (previous: WordTrim) => WordTrim) => void
): {
  dragging: TrimHandleName | null;
  moveHandle(handle: TrimHandleName, targetWord: number): void;
  handleProps(handle: TrimHandleName, at: number): {
    onPointerDown(event: React.PointerEvent<HTMLButtonElement>): void;
    onPointerMove(event: React.PointerEvent<HTMLButtonElement>): void;
    onPointerUp(event: React.PointerEvent<HTMLButtonElement>): void;
    onPointerCancel(event: React.PointerEvent<HTMLButtonElement>): void;
    onLostPointerCapture(): void;
    onKeyDown(event: React.KeyboardEvent<HTMLButtonElement>): void;
  };
} {
  // State rather than a ref: the handlers below are created during render, and
  // mutating a ref there is what the React Compiler rules forbid.
  const [dragging, setDragging] = useState<TrimHandleName | null>(null);

  const moveHandle = useCallback(
    (handle: TrimHandleName, targetWord: number) => {
      setTrim((previous) =>
        handle === "start"
          ? moveTrimStart(words, previous, targetWord)
          : moveTrimEnd(words, previous, targetWord)
      );
    },
    [words, setTrim]
  );

  const wordIndexAt = (clientX: number, clientY: number): number | null => {
    const element = document.elementFromPoint(clientX, clientY);
    const wordEl = element?.closest<HTMLElement>("[data-trim-index]");
    if (!wordEl) return null;
    const index = Number.parseInt(wordEl.dataset.trimIndex ?? "", 10);
    return Number.isInteger(index) ? index : null;
  };

  const release = (event: React.PointerEvent<HTMLButtonElement>): void => {
    setDragging(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const handleProps = (handle: TrimHandleName, at: number) => ({
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
    onPointerUp: release,
    // A gesture interrupted by the system — an incoming call, a browser
    // back-swipe — fires cancel and never up. Without these two the handle
    // stays armed and the next stray move drags it.
    onPointerCancel: release,
    onLostPointerCapture: () => setDragging(null),
    onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => {
      const step = event.shiftKey ? COARSE_STEP : 1;
      // RTL text: visually-right (ArrowRight) is one word EARLIER. This is the
      // convention in both clip UIs; the overview strip is a time axis, not
      // text, and deliberately keeps the opposite one.
      if (event.key === "ArrowRight") {
        event.preventDefault();
        moveHandle(handle, at - step);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        moveHandle(handle, at + step);
      } else if (event.key === "Home") {
        event.preventDefault();
        moveHandle(handle, 0);
      } else if (event.key === "End") {
        event.preventDefault();
        moveHandle(handle, words.length - 1);
      }
    },
  });

  return { dragging, moveHandle, handleProps };
}
