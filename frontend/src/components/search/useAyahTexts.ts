"use client";

import { useEffect, useState } from "react";
import { getAyah } from "@/lib/api";
import { ayahKey } from "@/lib/smart-answer";
import type { SmartAyah } from "@/types/models";

const SURAH_MAX = 114;
const AYAH_MAX = 286;

/** Module-level so a verse fetched once is never fetched again on the page. */
const fetched = new Map<string, Promise<SmartAyah | null>>();

function fetchAyah(surah: number, ayah: number): Promise<SmartAyah | null> {
  const key = ayahKey(surah, ayah);
  let pending = fetched.get(key);
  if (pending === undefined) {
    pending = getAyah(surah, ayah)
      .then((detail) => ({
        surah: detail.surah,
        ayah: detail.number,
        // The verse page payload has no surah name; the inline caption then
        // shows the number alone rather than guessing.
        surah_name_ar: "",
        text_uthmani: detail.text_uthmani,
      }))
      .catch(() => null);
    fetched.set(key, pending);
  }
  return pending;
}

/**
 * Canonical verse text for every `[[ayah:S:A]]` the answer may render.
 *
 * `hydrated` (the response's `ayah_refs`, filled server-side from the quran
 * app) answers almost everything; a placeholder the response did not cover
 * falls back to the verse endpoint — validated, deduplicated, cached. Only
 * `text_uthmani` from either source ever reaches the DOM.
 */
export function useAyahTexts(
  hydrated: SmartAyah[],
  wanted: { surah: number; ayah: number }[],
): (surah: number, ayah: number) => SmartAyah | null {
  const [extra, setExtra] = useState<Record<string, SmartAyah>>({});
  const known = new Map(hydrated.map((item) => [ayahKey(item.surah, item.ayah), item]));
  const missingKey = wanted
    .filter(
      ({ surah, ayah }) =>
        surah >= 1 && surah <= SURAH_MAX && ayah >= 1 && ayah <= AYAH_MAX &&
        !known.has(ayahKey(surah, ayah)),
    )
    .map(({ surah, ayah }) => ayahKey(surah, ayah))
    .join(",");

  useEffect(() => {
    if (missingKey === "") return;
    let cancelled = false;
    void Promise.all(
      missingKey.split(",").map(async (key) => {
        const [surah, ayah] = key.split(":").map(Number);
        return [key, await fetchAyah(surah, ayah)] as const;
      }),
    ).then((entries) => {
      if (cancelled) return;
      setExtra((previous) => {
        const next = { ...previous };
        for (const [key, value] of entries) if (value !== null) next[key] = value;
        return next;
      });
    });
    return () => {
      cancelled = true;
    };
  }, [missingKey]);

  return (surah, ayah) => known.get(ayahKey(surah, ayah)) ?? extra[ayahKey(surah, ayah)] ?? null;
}
