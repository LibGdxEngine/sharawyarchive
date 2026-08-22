import { cache } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import CopyAyahLink from "@/components/CopyAyahLink";
import ErrorNote from "@/components/ErrorNote";
import {
  AyahSeal,
  HeroCorners,
  HeroLattice,
  OrnamentDivider,
} from "@/components/surah/SurahOrnaments";
import { getAyah, getSurah, getSurahs } from "@/lib/api";
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

/** Names for the previous/next surah links at the foot of the page. */
const loadSurahNames = cache(() => getSurahs());

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

/** Chevron pointing in the reading direction: right = previous (RTL back). */
function ChevronRight() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
      className="h-3.5 w-3.5"
    >
      <path
        d="M6.5 3.5 12 8l-5.5 4.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

/** Chevron pointing after the text flow: left = next (RTL forward). */
function ChevronLeft() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden
      className="h-3.5 w-3.5"
    >
      <path
        d="M9.5 3.5 4 8l5.5 4.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
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
      <main className="reading-column page-shell pt-8">
        <ErrorNote />
      </main>
    );
  }

  const { count, page_size: pageSize } = surah.ayahs;
  const results = surah.ayahs.results as PageAyah[];
  const lastPage = Math.max(1, Math.ceil(count / Math.max(1, pageSize)));

  // Neighbour surah names for the foot links. Best-effort: if the index
  // fetch fails the links still render, labelled by number only.
  let prevSurahName: string | null = null;
  let nextSurahName: string | null = null;
  try {
    const index = await loadSurahNames();
    prevSurahName =
      index.find((entry) => entry.number === surahNumber - 1)?.name_ar ?? null;
    nextSurahName =
      index.find((entry) => entry.number === surahNumber + 1)?.name_ar ?? null;
  } catch {
    // Names are decoration; the numbered links below still work.
  }

  return (
    <main className="surah-page reading-column page-shell pt-10">
      {/* The illuminated opening panel: surah name framed by the star
          lattice, corner flourishes and an eight-point divider. */}
      <header className="surah-hero">
        <HeroLattice />
        <HeroLattice flip />
        <HeroCorners />
        <span aria-hidden className="surah-hero-halo" />
        <p className="relative text-xs font-medium tracking-[0.2em] text-[var(--sp-gold-deep)]">
          سُورَة
        </p>
        <h1 className="quran-text relative mt-1 text-4xl leading-[1.6] text-[var(--sp-quran-ink)] sm:text-5xl">
          {surah.name_ar}
        </h1>
        <OrnamentDivider className="relative mx-auto mt-5 max-w-52" />
        <p className="relative mt-5 flex flex-wrap items-center justify-center gap-2">
          <span className="sp-badge sp-badge--gold">
            {surah.revelation_place === "makkah" ? "مكية" : "مدنية"}
          </span>
          <span className="sp-badge">
            {toArabicIndic(surah.ayah_count)} آية
          </span>
        </p>
      </header>

      {/* The basmala opens every surah's reading except Al-Fatihah (where
          it is ayah 1, already in the text) and At-Tawbah (classically
          without one). */}
      {surahNumber !== 1 && surahNumber !== 9 ? (
        <div className="surah-basmala-wrap mt-10 flex items-center gap-5">
          <span aria-hidden className="sp-rule" />
          <p className="quran-text text-center text-[1.7rem] leading-[2] text-[var(--sp-quran-ink)]">
            بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ
          </p>
          <span aria-hidden className="sp-rule sp-rule--mirror" />
        </div>
      ) : null}

      <ol className="mt-6 space-y-1">
        {results.map((ayah, i) => {
          const segments = ayah.segments ?? [];
          const isActive = ayah.number === activeAyah;
          return (
            <li
              key={ayah.number}
              id={`ayah-${ayah.number}`}
              aria-current={isActive ? "true" : undefined}
              style={{ animationDelay: `${220 + Math.min(i, 20) * 45}ms` }}
              className={`surah-ayah scroll-mt-28${
                isActive ? " surah-ayah--active" : ""
              }`}
            >
              <div className="flex gap-3 py-1 sm:gap-4">
                <AyahSeal number={ayah.number} />
                <div className="min-w-0 flex-1">
                  <p className="surah-ayah-text quran-text text-[1.55rem] leading-[2.1] sm:text-2xl">
                    {ayah.text_uthmani}{" "}
                    <span className="surah-ayah-mark text-lg">
                      ﴿{toArabicIndic(ayah.number)}﴾
                    </span>
                  </p>

                  <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
                    <Link
                      href={`/surah/${surahNumber}/ayah/${ayah.number}`}
                      className="sp-link"
                    >
                      صفحة الآية
                    </Link>
                    <CopyAyahLink surah={surahNumber} ayah={ayah.number} />
                    <span className="text-[var(--color-ink-faint)]">
                      الجزء {toArabicIndic(ayah.juz)} · صفحة{" "}
                      {toArabicIndic(ayah.page)}
                    </span>
                    {ayah.sajda ? (
                      <span className="sp-badge sp-badge--gold">سجدة</span>
                    ) : null}
                  </div>

                  {segments.length > 0 ? (
                    <ul className="mt-3 space-y-2">
                      {segments.map((segment) => (
                        <li
                          key={segment.id}
                          className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-[var(--color-ink-muted)]"
                        >
                          <Link
                            href={`/listen/${segment.id}`}
                            className="sp-chip"
                          >
                            <svg
                              viewBox="0 0 10 10"
                              width="9"
                              height="9"
                              aria-hidden
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
                          {toArabicIndic(
                            ayah.segment_count - segments.length
                          )}
                          + مقاطع أخرى تغطي هذه الآية
                        </li>
                      ) : null}
                    </ul>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      {lastPage > 1 ? (
        <nav
          aria-label="صفحات السورة"
          className="mt-10 flex items-center justify-between gap-3"
        >
          {page > 1 ? (
            <Link
              href={`/surah/${surahNumber}?page=${page - 1}`}
              className="sp-chip"
            >
              <ChevronRight />
              الصفحة السابقة
            </Link>
          ) : (
            <span />
          )}
          <span className="flex items-center gap-3 text-xs text-[var(--color-ink-faint)]">
            <span aria-hidden className="sp-rule w-10 flex-none" />
            {toArabicIndic(page)} / {toArabicIndic(lastPage)}
            <span
              aria-hidden
              className="sp-rule sp-rule--mirror w-10 flex-none"
            />
          </span>
          {page < lastPage ? (
            <Link
              href={`/surah/${surahNumber}?page=${page + 1}`}
              className="sp-chip"
            >
              الصفحة التالية
              <ChevronLeft />
            </Link>
          ) : (
            <span />
          )}
        </nav>
      ) : null}

      <nav
        aria-label="التنقل بين السور"
        className="mt-10 grid gap-3 sm:grid-cols-2"
      >
        {surahNumber > 1 ? (
          <Link
            href={`/surah/${surahNumber - 1}`}
            className="surah-nav-card surah-nav-card--prev flex items-center gap-4"
          >
            <span aria-hidden className="nav-chevron">
              <ChevronRight />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-xs text-[var(--color-ink-faint)]">
                السورة السابقة
              </span>
              <span className="nav-name quran-text mt-0.5 block text-xl leading-[1.8]">
                {prevSurahName ?? `سورة ${surahNumber - 1}`}
              </span>
            </span>
          </Link>
        ) : (
          <span aria-hidden className="hidden sm:block" />
        )}
        {surahNumber < 114 ? (
          <Link
            href={`/surah/${surahNumber + 1}`}
            className="surah-nav-card surah-nav-card--next flex items-center gap-4 text-end"
          >
            <span className="min-w-0 flex-1">
              <span className="block text-xs text-[var(--color-ink-faint)]">
                السورة التالية
              </span>
              <span className="nav-name quran-text mt-0.5 block text-xl leading-[1.8]">
                {nextSurahName ?? `سورة ${surahNumber + 1}`}
              </span>
            </span>
            <span aria-hidden className="nav-chevron">
              <ChevronLeft />
            </span>
          </Link>
        ) : (
          <span aria-hidden className="hidden sm:block" />
        )}
      </nav>
    </main>
  );
}
