import Link from "next/link";
import { notFound } from "next/navigation";
import ErrorNote from "@/components/ErrorNote";
import SiteHeader from "@/components/SiteHeader";
import { getAyah, getSurah } from "@/lib/api";
import { kindLabel, toArabicIndic } from "@/lib/format";
import type { SegmentSummary, SurahDetail } from "@/types/models";

export const dynamic = "force-dynamic";

interface SurahPageProps {
  params: Promise<{ n: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

/**
 * Segments covering each ayah on this page.
 *
 * The surah endpoint reports only a `segment_count` per ayah, so the ids come
 * from /api/ayahs/{surah}/{ayah}/. Fetched with allSettled: a missing ayah
 * response costs that ayah its listen links, never the whole page.
 */
async function loadSegmentsByAyah(
  surah: number,
  ayahNumbers: number[]
): Promise<Map<number, SegmentSummary[]>> {
  const settled = await Promise.allSettled(
    ayahNumbers.map((number) => getAyah(surah, number))
  );
  const byAyah = new Map<number, SegmentSummary[]>();
  settled.forEach((result, index) => {
    if (result.status === "fulfilled" && result.value.segments.length > 0) {
      byAyah.set(ayahNumbers[index], result.value.segments);
    }
  });
  return byAyah;
}

export default async function SurahPage({
  params,
  searchParams,
}: SurahPageProps) {
  const { n } = await params;
  const surahNumber = Number.parseInt(n, 10);
  if (!Number.isInteger(surahNumber) || surahNumber < 1 || surahNumber > 114) {
    notFound();
  }

  const rawPage = (await searchParams).page;
  const pageValue = Array.isArray(rawPage) ? rawPage[0] : rawPage;
  const parsedPage = Number.parseInt(pageValue ?? "1", 10);
  const page = Number.isInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1;

  let surah: SurahDetail;
  try {
    surah = await getSurah(surahNumber, page);
  } catch {
    return (
      <>
        <SiteHeader />
        <main className="reading-column page-shell pt-8">
          <ErrorNote />
        </main>
      </>
    );
  }

  const { count, page_size: pageSize, results } = surah.ayahs;
  const lastPage = Math.max(1, Math.ceil(count / Math.max(1, pageSize)));
  const segmentsByAyah = await loadSegmentsByAyah(
    surahNumber,
    results.filter((ayah) => ayah.segment_count > 0).map((ayah) => ayah.number)
  );

  return (
    <>
      <SiteHeader />
      <main className="reading-column page-shell pt-8">
        <h1 className="quran-text text-3xl leading-normal">{surah.name_ar}</h1>
        <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
          {surah.revelation_place === "makkah" ? "مكية" : "مدنية"} ·{" "}
          {toArabicIndic(surah.ayah_count)} آية
        </p>

        <ol className="mt-8">
          {results.map((ayah) => {
            const segments = segmentsByAyah.get(ayah.number);
            return (
              <li
                key={ayah.number}
                className="border-b border-[var(--color-border-subtle)] py-5"
              >
                <p className="quran-text text-2xl">
                  {ayah.text_uthmani}{" "}
                  <span className="text-lg text-[var(--color-ink-faint)]">
                    ﴿{toArabicIndic(ayah.number)}﴾
                  </span>
                </p>

                {segments ? (
                  <ul className="mt-3 space-y-1">
                    {segments.map((segment) => (
                      <li
                        key={segment.id}
                        className="flex flex-wrap items-baseline gap-x-3 text-xs text-[var(--color-ink-muted)]"
                      >
                        <Link
                          href={`/listen/${segment.id}`}
                          className="text-[var(--color-ink)]"
                        >
                          استمع
                        </Link>
                        <span>{kindLabel(segment.kind)}</span>
                        <span className="truncate text-[var(--color-ink-faint)]">
                          {segment.title}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ol>

        <nav className="mt-8 flex items-center justify-between text-sm">
          {page > 1 ? (
            <Link href={`/surah/${surahNumber}?page=${page - 1}`}>
              الصفحة السابقة
            </Link>
          ) : (
            <span />
          )}
          <span className="text-xs text-[var(--color-ink-faint)]">
            {toArabicIndic(page)} / {toArabicIndic(lastPage)}
          </span>
          {page < lastPage ? (
            <Link href={`/surah/${surahNumber}?page=${page + 1}`}>
              الصفحة التالية
            </Link>
          ) : (
            <span />
          )}
        </nav>
      </main>
    </>
  );
}
