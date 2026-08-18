import Link from "next/link";
import ErrorNote from "@/components/ErrorNote";
import SiteHeader from "@/components/SiteHeader";
import { getSurahs } from "@/lib/api";
import { toArabicIndic } from "@/lib/format";
import type { Surah } from "@/types/models";

export const dynamic = "force-dynamic";

export default async function SurahsPage() {
  let surahs: Surah[];
  try {
    surahs = await getSurahs();
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

  return (
    <>
      <SiteHeader />
      <main className="reading-column page-shell pt-8">
        <h1 className="text-lg font-semibold">فهرس السور</h1>
        <ul className="mt-6 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
          {surahs.map((surah) => (
            <li key={surah.number}>
              <Link
                href={`/surah/${surah.number}`}
                className="flex items-baseline justify-between gap-2 border-b border-[var(--color-border-subtle)] py-2"
              >
                <span className="quran-text text-lg leading-normal">
                  {surah.name_ar}
                </span>
                <span className="shrink-0 text-xs text-[var(--color-ink-faint)]">
                  {toArabicIndic(surah.ayah_count)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </main>
    </>
  );
}
