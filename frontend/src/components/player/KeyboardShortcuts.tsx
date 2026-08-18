"use client";

import { useEffect } from "react";
import { useAudioStore } from "@/lib/audio-store";
import { isTypingTarget } from "@/lib/keyboard-target";

const SEEK_STEP_MS = 10_000;

/**
 * App-wide keyboard transport. Lives in the root layout so the shortcuts work
 * from any route while audio is playing.
 *
 * ArrowRight is forward and ArrowLeft is back even though the document is RTL:
 * the arrows map to the timeline, not to the reading direction, and every
 * media player the listener already uses behaves this way.
 *
 * Transcript word buttons are not treated as typing targets — see
 * `isTypingTarget`. Their keys are handled here and the default is prevented,
 * which is also what stops Space from re-activating the focused word.
 */
export default function KeyboardShortcuts() {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTypingTarget(event.target)) return;

      if (event.key === "/") {
        const search = document.getElementById("site-search");
        if (search instanceof HTMLInputElement) {
          event.preventDefault();
          search.focus();
          search.select();
        }
        return;
      }

      const store = useAudioStore.getState();
      if (store.current === null) return;

      switch (event.key) {
        case " ":
        case "Spacebar":
          event.preventDefault();
          store.toggle();
          break;
        case "ArrowRight":
          event.preventDefault();
          store.seekBy(SEEK_STEP_MS);
          break;
        case "ArrowLeft":
          event.preventDefault();
          store.seekBy(-SEEK_STEP_MS);
          break;
        default:
          break;
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  return null;
}
