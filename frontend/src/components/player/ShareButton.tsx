"use client";

import { useState } from "react";
import { useAudioStore } from "@/lib/audio-store";

interface ShareButtonProps {
  segmentId: number;
}

/**
 * Copies a deep link to the current playback position: the page URL with the
 * live position written into `?t=<ms>`, which /listen reads back on load.
 */
export default function ShareButton({ segmentId }: ShareButtonProps) {
  const [copied, setCopied] = useState(false);

  const share = async () => {
    const { current, positionMs, _el } = useAudioStore.getState();
    const atMs =
      current !== null && current.segmentId === segmentId && _el
        ? Math.floor(_el.currentTime * 1000)
        : positionMs;

    const url = new URL(window.location.href);
    url.searchParams.set("t", String(Math.max(0, atMs)));
    const href = url.toString();

    try {
      await navigator.clipboard.writeText(href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("انسخ الرابط", href);
    }
  };

  return (
    <button
      type="button"
      onClick={share}
      className={`listen-chip${copied ? " listen-chip--active" : ""}`}
    >
      {copied ? "نُسخ الرابط" : "مشاركة الموضع"}
    </button>
  );
}
