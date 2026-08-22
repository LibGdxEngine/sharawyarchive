"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import CopyAyahLink from "@/components/CopyAyahLink";
import { getSurah } from "@/lib/api";
import { kindLabel, toArabicIndic } from "@/lib/format";
import type { SurahDetail } from "@/types/models";

/**
 * Backend shape addition (`quran/serializers.py::SurahAyahSerializer`): every
 * ayah on a surah page carries the segments covering it, capped at five, with
 * `segment_count` still the uncapped total.
 */
export interface AyahSegmentRef {
  id: number;
  kind: "recitation" | "khawatir";
  title: string;
}

export type PageAyah = SurahDetail["ayahs"]["results"][number] & {
  segments?: AyahSegmentRef[];
};

interface SurahInfiniteScrollProps {
  surahNumber: number;
  activeAyah: number | null;
  initialAyahs: PageAyah[];
  /** The page the server rendered first (1, or the page holding `?ayah=`). */
  startPage: number;
  total: number;
  pageSize: number;
}

/**
 * Renders the ayahs of one surah as a continuously growing list. The server
 * supplies the first page; as the sentinel scrolls into view this client
 * fetches the next page and appends it, until every ayah is on screen.
 */
export default function SurahInfiniteScroll({
  surahNumber,
  activeAyah,
  initialAyahs,
  startPage,
  total,
  pageSize,
}: SurahInfiniteScrollProps) {
  const [ayahs, setAyahs] = useState<PageAyah[]>(initialAyahs);
  const [nextPage, setNextPage] = useState(startPage + 1);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const sentinelRef = useRef<HTMLDivElement>(null);

  const lastPage = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  const hasMore = nextPage <= lastPage;

  const loadMore = useCallback(async () => {
    if (loading || !hasMore) return;
    setLoading(true);
    setFailed(false);
    try {
      const res = await getSurah(surahNumber, nextPage);
      setAyahs((prev) => {
        const seen = new Set(prev.map((ayah) => ayah.number));
        const fresh = (res.ayahs.results as PageAyah[]).filter(
          (ayah) => !seen.has(ayah.number)
        );
        return [...prev, ...fresh];
      });
      setNextPage((page) => page + 1);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [loading, hasMore, nextPage, surahNumber]);

  useEffect(() => {
    const node = sentinelRef.current;
    if (!node || !hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { rootMargin: "600px 0px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hasMore, loadMore, nextPage]);

  return (
    <>
      <ol className="mt-8">
        {ayahs.map((ayah) => {
          const segments = ayah.segments ?? [];
          const isActive = ayah.number === activeAyah;
          return (
            <li
              key={ayah.number}
              id={`ayah-${ayah.number}`}
              aria-current={isActive ? "true" : undefined}
              className={`scroll-mt-24 border-b border-[var(--color-border-subtle)] py-5${
                isActive
                  ? " -mx-4 rounded-md bg-[var(--color-accent-bg)] px-4"
                  : ""
              }`}
            >
              <p className="quran-text text-2xl">
                {ayah.text_uthmani}{" "}
                <span className="text-lg text-[var(--color-ink-faint)]">
                  ﴿{toArabicIndic(ayah.number)}﴾
                </span>
              </p>

              <div className="mt-2 flex justify-end gap-3">
                <Link
                  href={`/surah/${surahNumber}/ayah/${ayah.number}`}
                  className="text-xs text-[var(--color-ink-faint)] underline-offset-4 hover:underline"
                >
                  صفحة الآية
                </Link>
                <CopyAyahLink surah={surahNumber} ayah={ayah.number} />
              </div>

              {segments.length > 0 ? (
                <ul className="mt-3 space-y-1.5">
                  {segments.map((segment) => (
                    <li
                      key={segment.id}
                      className="flex flex-wrap items-center gap-x-3 text-xs text-[var(--color-ink-muted)]"
                    >
                      <Link
                        href={`/listen/${segment.id}`}
                        className="inline-flex shrink-0 items-center gap-1.5 rounded border border-[var(--color-border)] px-2 py-0.5 text-[var(--color-ink)] hover:bg-[var(--color-bg-subtle)]"
                      >
                        <svg
                          viewBox="0 0 10 10"
                          width="9"
                          height="9"
                          aria-hidden="true"
                          className="fill-current"
                        >
                          <path d="M2 1.2v7.6L8.6 5z" />
                        </svg>
                        استمع
                      </Link>
                      <span>{kindLabel(segment.kind)}</span>
                      <span className="truncate text-[var(--color-ink-faint)]">
                        {segment.title}
                      </span>
                    </li>
                  ))}
                  {ayah.segment_count > segments.length ? (
                    <li className="text-xs text-[var(--color-ink-faint)]">
                      {toArabicIndic(ayah.segment_count - segments.length)}+
                      مقاطع أخرى تغطي هذه الآية
                    </li>
                  ) : null}
                </ul>
              ) : null}
            </li>
          );
        })}
      </ol>

      {hasMore ? (
        <div
          ref={sentinelRef}
          className="flex min-h-16 items-center justify-center py-4 text-sm text-[var(--color-ink-muted)]"
        >
          {failed ? (
            <button
              type="button"
              onClick={() => void loadMore()}
              className="underline-offset-4 hover:underline"
            >
              تعذّر التحميل — أعد المحاولة
            </button>
          ) : (
            <span>{loading ? "جارٍ تحميل الآيات…" : ""}</span>
          )}
        </div>
      ) : (
        <p className="py-4 text-center text-xs text-[var(--color-ink-faint)]">
          نهاية السورة
        </p>
      )}
    </>
  );
}
