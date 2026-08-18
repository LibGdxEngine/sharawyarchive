"use client";

import { useEffect } from "react";
import { useAudioStore } from "@/lib/audio-store";

const SEEK_STEP_MS = 10_000;

/** Typing, or driving a control that already owns these keys. */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    tag === "BUTTON" ||
    tag === "A"
  );
}

/**
 * App-wide keyboard transport. Lives in the root layout so the shortcuts work
 * from any route while audio is playing.
 *
 * ArrowRight is forward and ArrowLeft is back even though the document is RTL:
 * the arrows map to the timeline, not to the reading direction, and every
 * media player the listener already uses behaves this way.
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
