import { cache } from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import ErrorNote from "@/components/ErrorNote";
import AyahCard from "@/components/verse/AyahCard";
import VerseBodyTheme from "@/components/verse/VerseBodyTheme";
import { amiriFont } from "@/fonts";
import { ApiError, getAyah, getSurah } from "@/lib/api";
import { SITE_NAME } from "@/lib/site";
import type { AyahDetail } from "@/types/models";
import VersePageClient from "./VersePageClient";

export const dynamic = "force-dynamic";

type Query = { [key: string]: string | string[] | undefined };

interface AyahVersePageProps {
  params: Promise<{ n: string; m: string }>;
  searchParams: Promise<Query>;
}

/**
 * The verse page — `/surah/{n}/ayah/{m}`. One ayah, every segment that
 * covers it, verified Tanzil text interleaved with the machine transcript
 * (the gold "Sharawy Player" theme from DESIGN.md).
 */

function readPositiveInt(raw: string | string[] | undefined): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

/** `?t=<ms>` deep-link position, or null when absent or malformed. */
function parseStartMs(raw: string | string[] | undefined): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined) return null;
  const ms = Number.parseInt(value, 10);
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

/** Meta descriptions get truncated by search engines anyway. */
function clamp(text: string, limit = 120): string {
  return text.length <= limit ? text : `${text.slice(0, limit).trimEnd()}…`;
}

const loadAyah = cache((surah: number, ayah: number): Promise<AyahDetail> =>
  getAyah(surah, ayah)
);

async function loadSurahName(surah: number): Promise<string | null> {
  try {
    return (await getSurah(surah)).name_ar;
  } catch {
    return null;
  }
}

export async function generateMetadata({
  params,
}: AyahVersePageProps): Promise<Metadata> {
  const { n, m } = await params;
  const surahNumber = Number.parseInt(n, 10);
  const ayahNumber = Number.parseInt(m, 10);

  const fallback: Metadata = {
    title: `آية — ${SITE_NAME}`,
    alternates: { canonical: `/surah/${n}/ayah/${m}` },
  };
  if (
    !Number.isInteger(surahNumber) ||
    surahNumber < 1 ||
    surahNumber > 114 ||
    !Number.isInteger(ayahNumber) ||
    ayahNumber < 1
  ) {
    return fallback;
  }

  let ayah: AyahDetail;
  try {
    ayah = await loadAyah(surahNumber, ayahNumber);
  } catch {
    return fallback;
  }

  const reference = `سورة ${ayah.surah} · الآية ${ayahNumber}`;
  const title = `${reference} — ${SITE_NAME}`;
  const description = `${reference}: ${clamp(
    ayah.text_uthmani
  )} — تلاوات وخواطر الشيخ محمد متولي الشعراوي`;

  return {
    title,
    description,
    alternates: { canonical: `/surah/${surahNumber}/ayah/${ayahNumber}` },
    openGraph: {
      type: "website",
      siteName: SITE_NAME,
      locale: "ar_AR",
      title,
      description,
      url: `/surah/${surahNumber}/ayah/${ayahNumber}`,
    },
  };
}

export default async function AyahVersePage({
  params,
  searchParams,
}: AyahVersePageProps) {
  const { n, m } = await params;
  const surahNumber = Number.parseInt(n, 10);
  const ayahNumber = Number.parseInt(m, 10);
  if (
    !Number.isInteger(surahNumber) ||
    surahNumber < 1 ||
    surahNumber > 114 ||
    !Number.isInteger(ayahNumber) ||
    ayahNumber < 1
  ) {
    notFound();
  }

  let ayah: AyahDetail;
  try {
    ayah = await loadAyah(surahNumber, ayahNumber);
  } catch (error) {
    // Out-of-range ayah: a real 404. Anything else: the API is down, and the
    // quiet failure state is the honest answer.
    if (error instanceof ApiError && error.status === 404) notFound();
    return (
      <main className="reading-column page-shell pt-8">
        <ErrorNote />
      </main>
    );
  }

  const query = await searchParams;
  const surahName = await loadSurahName(surahNumber);
  const segments = ayah.segments;

  // ?seg= wins when it names a segment that actually covers this ayah;
  // otherwise the first covering segment is the default.
  const requested = readPositiveInt(query.seg);
  const initialSegment =
    segments.find((entry) => entry.id === requested) ?? segments[0];
  const startMs = parseStartMs(query.t);

  return (
    <div className={`verse-theme ${amiriFont.variable}`}>
      <VerseBodyTheme />
      <main className="reading-column page-shell pt-8">
        <p className="mb-6 text-xs">
          <Link
            href={`/surah/${surahNumber}?ayah=${ayahNumber}`}
            className="text-[var(--color-ink-muted)] underline-offset-4 hover:underline"
          >
            سورة {surahName ?? surahNumber} — العودة إلى صفحة السورة
          </Link>
        </p>

        {initialSegment === undefined ? (
          <>
            <AyahCard
              ayah={{ number: ayah.number, textUthmani: ayah.text_uthmani }}
              match={null}
              activeWordIndex={-1}
              surahName={surahName}
              surahNumber={surahNumber}
            />
            <p className="text-sm leading-relaxed text-[var(--color-ink-muted)]">
              لا تتوفّر تسجيلات تغطي هذه الآية بعد — سيظهر الاستماع هنا فور
              إضافة المقاطع.
            </p>
          </>
        ) : (
          <VersePageClient
            surah={surahNumber}
            ayahNumber={ayahNumber}
            focusAyah={{ number: ayah.number, textUthmani: ayah.text_uthmani }}
            segments={segments}
            initialSegmentId={initialSegment.id}
            startMs={startMs}
            surahName={surahName}
          />
        )}
      </main>
    </div>
  );
}
