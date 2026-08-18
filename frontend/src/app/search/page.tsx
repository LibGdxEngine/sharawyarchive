import Link from "next/link";
import ChunkResultList from "@/components/ChunkResultList";
import ErrorNote from "@/components/ErrorNote";
import SiteHeader from "@/components/SiteHeader";
import { search } from "@/lib/api";
import { toArabicIndic } from "@/lib/format";
import type { SearchResponse } from "@/types/models";

// Search responses are `Cache-Control: no-store` (API_CONTRACT.md) and depend
// entirely on the query string.
export const dynamic = "force-dynamic";

interface SearchPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(raw: string | string[] | undefined): string {
  return (Array.isArray(raw) ? raw[0] : raw) ?? "";
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const params = await searchParams;
  const query = firstValue(params.q).trim();

  if (query === "") {
    return (
      <>
        <SiteHeader />
        <main className="reading-column page-shell pt-8">
          <p className="text-sm text-[var(--color-ink-muted)]">
            اكتب عبارة في حقل البحث للبدء.
          </p>
        </main>
      </>
    );
  }

  let response: SearchResponse;
  try {
    response = await search({ q: query });
  } catch {
    return (
      <>
        <SiteHeader defaultQuery={query} />
        <main className="reading-column page-shell pt-8">
          <ErrorNote />
        </main>
      </>
    );
  }

  return (
    <>
      <SiteHeader defaultQuery={query} />
      <main className="reading-column page-shell pt-8">
        <h1 className="text-lg font-semibold">نتائج البحث عن «{query}»</h1>
        <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
          {response.total} نتيجة
        </p>

        {response.ayah_matches.length > 0 ? (
          <section className="mt-8">
            <h2 className="text-xs text-[var(--color-ink-muted)]">
              آيات مطابقة
            </h2>
            <ul className="mt-2 divide-y divide-[var(--color-border-subtle)]">
              {response.ayah_matches.map((ayah) => (
                <li key={`${ayah.surah}:${ayah.number}`} className="py-4">
                  <p className="quran-text text-2xl">
                    {ayah.text_uthmani}{" "}
                    <span className="text-base text-[var(--color-ink-faint)]">
                      ﴿{toArabicIndic(ayah.number)}﴾
                    </span>
                  </p>
                  <Link
                    href={`/surah/${ayah.surah}`}
                    className="mt-1 inline-block text-xs text-[var(--color-ink-muted)]"
                  >
                    سورة {ayah.surah_name_ar}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="mt-8">
          <h2 className="text-xs text-[var(--color-ink-muted)]">
            مقاطع من الأرشيف
          </h2>
          <ChunkResultList
            results={response.results}
            emptyLabel="لا توجد مقاطع مطابقة لهذه العبارة."
          />
        </section>
      </main>
    </>
  );
}
