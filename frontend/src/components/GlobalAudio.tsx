"use client";

import { useEffect, useRef } from "react";
import { useAudioStore } from "@/lib/audio-store";

/**
 * GlobalAudio — renders the single hidden <audio> element that persists for
 * the entire app lifetime and wires it into the Zustand audio store.
 *
 * Mount once in the root layout, inside <body>.
 */
export default function GlobalAudio() {
  const ref = useRef<HTMLAudioElement>(null);
  const bindAudio = useAudioStore((s) => s.bindAudio);
  const current = useAudioStore((s) => s.current);

  // Wire the element into the store on mount
  useEffect(() => {
    if (ref.current) {
      bindAudio(ref.current);
    }
  }, [bindAudio]);

  // Media Session API — update metadata and register action handlers
  useEffect(() => {
    if (typeof window === "undefined" || !("mediaSession" in navigator)) return;
    if (!current) return;

    navigator.mediaSession.metadata = new MediaMetadata({
      title: current.title,
      artist: "الشيخ محمد متولي الشعراوي",
      album: "خواطر الشعراوي",
    });

    const store = useAudioStore.getState;

    navigator.mediaSession.setActionHandler("play", () => {
      store().play();
    });
    navigator.mediaSession.setActionHandler("pause", () => {
      store().pause();
    });
    navigator.mediaSession.setActionHandler("seekbackward", (details) => {
      store().seekBy(-((details.seekOffset ?? 10) * 1000));
    });
    navigator.mediaSession.setActionHandler("seekforward", (details) => {
      store().seekBy((details.seekOffset ?? 10) * 1000);
    });
    navigator.mediaSession.setActionHandler("seekto", (details) => {
      if (details.seekTime !== undefined) {
        store().seekMs(Math.floor(details.seekTime * 1000));
      }
    });
  }, [current]);

  return (
    <audio ref={ref} preload="metadata" style={{ display: "none" }} />
  );
}
