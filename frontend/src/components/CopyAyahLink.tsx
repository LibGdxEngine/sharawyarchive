"use client";

import { useEffect, useRef, useState } from "react";

interface CopyAyahLinkProps {
  surah: number;
  ayah: number;
}

/**
 * Copies the canonical /surah/{n}?ayah={m} URL — the same shape the sitemap
 * publishes, so a shared link opens this ayah highlighted at scroll.
 * Quiet on failure: clipboard needs a secure context and permission, and a
 * copy affordance is never worth an error state.
 */
export default function CopyAyahLink({ surah, ayah }: CopyAyahLinkProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    []
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(
        `${window.location.origin}/surah/${surah}?ayah=${ayah}`
      );
      setCopied(true);
      if (timer.current !== null) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1600);
    } catch {
      // No clipboard (insecure context, denied permission): leave the UI as is.
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={`نسخ رابط الآية ${ayah}`}
      className="text-xs text-[var(--color-ink-faint)] underline-offset-4 hover:underline"
    >
      {copied ? "نُسخ الرابط" : "نسخ الرابط"}
    </button>
  );
}
