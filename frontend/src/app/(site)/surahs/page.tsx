import ErrorNote from "@/components/ErrorNote";
import SurahIndexList from "@/components/SurahIndexList";
import { getSurahs } from "@/lib/api";
import { toArabicIndic } from "@/lib/format";
import { filtersFromParams } from "@/lib/surah-filter";
import type { Surah } from "@/types/models";

export const dynamic = "force-dynamic";

type Query = { [key: string]: string | string[] | undefined };

/** Pointed mihrab arch — the same niche motif the cards use. */
const ARCH_PATH =
  "M28 88 L28 44 C28 30 36 24 42 19 C46 15.5 50 10 50 6 C50 10 54 15.5 58 19 C64 24 72 30 72 44 L72 88 Z";
const FINIAL_PATH = "M50 0.5 L52.5 3 L50 5.5 L47.5 3 Z";

/** Gold line + miniated mihrab arch + line, the ornamental header divider. */
function OrnamentDivider() {
  return (
    <div
      aria-hidden
      className="flex items-center justify-center gap-4 text-[var(--surah-gold)]"
    >
      <span className="h-px w-16 bg-gradient-to-l from-[var(--surah-gold)] to-transparent" />
      <svg viewBox="0 0 100 100" className="h-7 w-7" fill="currentColor">
        <path d={FINIAL_PATH} />
        <path d={ARCH_PATH} />
      </svg>
      <span className="h-px w-16 bg-gradient-to-r from-[var(--surah-gold)] to-transparent" />
    </div>
  );
}

export default async function SurahsPage({
  searchParams,
}: {
  searchParams: Promise<Query>;
}) {
  // Filters come from the URL so a shared link renders already narrowed,
  // server-side, instead of flashing all 114 cards first.
  const initialFilters = filtersFromParams(await searchParams);

  let surahs: Surah[];
  try {
    surahs = await getSurahs();
  } catch {
    return (
      <main className="surahs reading-column page-shell pt-8">
        <ErrorNote />
      </main>
    );
  }

  const totalAyahs = surahs.reduce((sum, s) => sum + s.ayah_count, 0);
  const totalSegments = surahs.reduce((sum, s) => sum + s.segment_count, 0);

  return (
    <main className="surahs surahs-bg page-shell">
      <div className="mx-auto w-full max-w-6xl px-4 pt-10 sm:px-6 lg:pt-14">
        <header className="text-center">
          <OrnamentDivider />
          <h1 className="mt-5 text-3xl font-semibold text-[var(--color-ink)] sm:text-4xl">
            فهرس السور
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-[var(--color-ink-muted)]">
            اختر سورةً لاستعراض تلاوتها وخواطر الشيخ الشعراوي عليها
          </p>
          <p className="mt-4 text-xs text-[var(--color-ink-faint)]">
            <span className="text-[var(--surah-gold-deep)]">
              {toArabicIndic(surahs.length)}
            </span>{" "}
            سورة ·{" "}
            <span className="text-[var(--surah-gold-deep)]">
              {toArabicIndic(totalAyahs)}
            </span>{" "}
            آية ·{" "}
            <span className="text-[var(--surah-gold-deep)]">
              {toArabicIndic(totalSegments)}
            </span>{" "}
            مقطع
          </p>
        </header>

        <SurahIndexList surahs={surahs} initialFilters={initialFilters} />
      </div>
    </main>
  );
}
