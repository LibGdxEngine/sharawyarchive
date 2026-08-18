import { cache } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ErrorNote from "@/components/ErrorNote";
import SiteHeader from "@/components/SiteHeader";
import { getAyah, getSurah } from "@/lib/api";
import { kindLabel, toArabicIndic } from "@/lib/format";
import { SITE_NAME } from "@/lib/site";
import type { SurahDetail } from "@/types/models";

export const dynamic = "force-dynamic";

type Query = { [key: string]: string | string[] | undefined };

interface SurahPageProps {
  params: Promise<{ n: string }>;
  searchParams: Promise<Query>;
}

/**
 * Backend shape addition (`quran/serializers.py::SurahAyahSerializer`): every
 * ayah on a surah page now carries the segments covering it, capped at five,
 * with `segment_count` still the uncapped total.
 *
 * Declared here rather than in `types/models.ts` so the change stays additive.
 */
interface AyahSegmentRef {
  id: number;
  kind: "recitation" | "khawatir";
  title: string;
}

type PageAyah = SurahDetail["ayahs"]["results"][number] & {
  segments?: AyahSegmentRef[];
};

/**
 * Fixed by API_CONTRACT.md (`GET /api/surahs/{n}/` is always 20 per page) and
 * not client-tunable, so we can map an ayah number to its page before the
 * fetch that would otherwise tell us `page_size`.
 */
const AYAH_PAGE_SIZE = 20;

/**
 * Deduplicates the surah fetch between `generateMetadata` and the render.
 * Both derive the page the same way, so the two calls hit one request.
 */
const loadSurah = cache(
  (surahNumber: number, page: number): Promise<SurahDetail> =>
    getSurah(surahNumber, page)
);

function readNumber(query: Query, key: string): number | null {
  const raw = query[key];
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/**
 * Which page to render. `?ayah=` without `?page=` — the shape every sitemap
 * entry uses — resolves to the page that actually contains the verse, so the
 * anchor and the metadata describe the same content.
 */
function readPage(query: Query): number {
  const page = readNumber(query, "page");
  if (page !== null) return page;
  const ayah = readNumber(query, "ayah");
  return ayah === null ? 1 : Math.ceil(ayah / AYAH_PAGE_SIZE);
}

/** Meta descriptions get truncated by search engines anyway. */
function clamp(text: string, limit = 120): string {
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}…`;
}

export async function generateMetadata({
  params,
  searchParams,
}: SurahPageProps): Promise<Metadata> {
  const { n } = await params;
  const query = await searchParams;
  const surahNumber = Number.parseInt(n, 10);
  const ayahNumber = readNumber(query, "ayah");

  // Every ayah in the sitemap is /surah/{n}?ayah={m}; pinning the canonical to
  // /surah/{n} would collapse those 6 236 URLs onto 114 pages.
  const canonicalFor = (ayah: number | null): string =>
    ayah === null
      ? `/surah/${surahNumber}`
      : `/surah/${surahNumber}?ayah=${ayah}`;

  // The surah name comes from the API, which may be unreachable — fall back to
  // a static title rather than failing the render.
  const fallback: Metadata = {
    title: `سورة — ${SITE_NAME}`,
    alternates: {
      canonical:
        ayahNumber === null ? `/surah/${n}` : `/surah/${n}?ayah=${ayahNumber}`,
    },
  };
  if (!Number.isInteger(surahNumber) || surahNumber < 1 || surahNumber > 114) {
    return fallback;
  }

  let surah: SurahDetail;
  try {
    surah = await loadSurah(surahNumber, readPage(query));
  } catch {
    return fallback;
  }

  const ayah =
    ayahNumber !== null && ayahNumber <= surah.ayah_count ? ayahNumber : null;

  let title = `سورة ${surah.name_ar} — ${SITE_NAME}`;
  let description = `سورة ${surah.name_ar} · ${surah.ayah_count} آية · تلاوات وخواطر الشيخ محمد متولي الشعراوي مع تفريغ نصّي متزامن`;

  if (ayah !== null) {
    title = `سورة ${surah.name_ar} — الآية ${ayah} — ${SITE_NAME}`;
    let text = "";
    try {
      text = (await getAyah(surahNumber, ayah)).text_uthmani;
    } catch {
      text = "";
    }
    const reference = `سورة ${surah.name_ar} · الآية ${ayah}`;
    description = text
      ? `${reference}: ${clamp(text)} — تلاوات وخواطر الشيخ الشعراوي`
      : `${reference} · تلاوات وخواطر الشيخ محمد متولي الشعراوي مع تفريغ نصّي متزامن`;
  }

  return {
    title,
    description,
    alternates: { canonical: canonicalFor(ayah) },
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      locale: "ar_AR",
      title,
      description,
      url: canonicalFor(ayah),
    },
  };
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

  const query = await searchParams;
  const page = readPage(query);
  const activeAyah = readNumber(query, "ayah");

  let surah: SurahDetail;
  try {
    surah = await loadSurah(surahNumber, page);
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

  const { count, page_size: pageSize } = surah.ayahs;
  const results = surah.ayahs.results as PageAyah[];
  const lastPage = Math.max(1, Math.ceil(count / Math.max(1, pageSize)));

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

                {segments.length > 0 ? (
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
