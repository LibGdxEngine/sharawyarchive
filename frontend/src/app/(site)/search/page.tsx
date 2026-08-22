import Link from "next/link";
import ChunkResultList from "@/components/ChunkResultList";
import ErrorNote from "@/components/ErrorNote";
import { search } from "@/lib/api";
import { kindLabel, toArabicIndic } from "@/lib/format";
import type { SearchResponse, VerseMatch } from "@/types/models";

// Search responses are `Cache-Control: no-store` (API_CONTRACT.md) and depend
// entirely on the query string.
export const dynamic = "force-dynamic";

interface SearchPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function firstValue(raw: string | string[] | undefined): string {
  return (Array.isArray(raw) ? raw[0] : raw) ?? "";
}

function firstKind(
  raw: string | string[] | undefined,
): "recitation" | "khawatir" | undefined {
  const value = firstValue(raw);
  return value === "recitation" || value === "khawatir" ? value : undefined;
}

function verseItem(verse: VerseMatch) {
  return (
    <li key={`${verse.surah}:${verse.number}`} className="py-4">
      <p className="quran-text text-2xl">
        {verse.text_uthmani}{" "}
        <span className="text-base text-[var(--color-ink-faint)]">
          ﴿{toArabicIndic(verse.number)}﴾
        </span>
      </p>
      <Link
        href={`/surah/${verse.surah}?ayah=${verse.number}#ayah-${verse.number}`}
        className="mt-1 inline-block text-xs text-[var(--color-ink-muted)]"
      >
        سورة {verse.surah_name_ar} · الجزء {toArabicIndic(verse.juz)} · صفحة{" "}
        {toArabicIndic(verse.page)}
      </Link>
    </li>
  );
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const params = await searchParams;
  const query = firstValue(params.q).trim();
  const kind = firstKind(params.kind);

  if (query === "") {
    return (
      <main className="reading-column page-shell pt-8">
        <p className="text-sm text-[var(--color-ink-muted)]">
          اكتب عبارة في حقل البحث للبدء.
        </p>
      </main>
    );
  }

  let response: SearchResponse;
  try {
    response = await search({ q: query, kind });
  } catch {
    return (
      <main className="reading-column page-shell pt-8">
        <ErrorNote />
      </main>
    );
  }

  return (
    <main className="reading-column page-shell pt-8">
      <h1 className="text-lg font-semibold">
        نتائج البحث عن «{query}»
        {kind ? (
          <span className="text-sm font-normal text-[var(--color-ink-muted)]">
            {" "}
            — {kindLabel(kind)}
          </span>
        ) : null}
      </h1>
      <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
        {response.total} نتيجة
      </p>

      {/*
        Two kinds of text share this page and they must never read as one
        list: the block below is the mushaf, the block after it is what the
        recogniser heard. Hence the rule between them and the label on each.
      */}
      {response.ayah_matches.length > 0 ? (
        <section className="mt-8 border-b border-[var(--color-border)] pb-8">
          <h2 className="text-xs text-[var(--color-ink-muted)]">
            آيات مطابقة — من القرآن الكريم
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
                  href={`/surah/${ayah.surah}?ayah=${ayah.number}#ayah-${ayah.number}`}
                  className="mt-1 inline-block text-xs text-[var(--color-ink-muted)]"
                >
                  سورة {ayah.surah_name_ar}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {response.verse_matches.length > 0 ? (
        <section className="mt-8 border-b border-[var(--color-border)] pb-8">
          <h2 className="text-xs text-[var(--color-ink-muted)]">
            آيات مطابقة — بحث نصّي في المصحف
          </h2>
          <ul className="mt-2 divide-y divide-[var(--color-border-subtle)]">
            {response.verse_matches.map((verse) => verseItem(verse))}
          </ul>
        </section>
      ) : null}

      <section className="mt-8">
        <h2 className="text-xs text-[var(--color-ink-muted)]">
          مقاطع من الأرشيف
        </h2>
        <ChunkResultList
          results={response.results}
          emptyLabel="لا توجد مقاطع مطابقة لهذه العبارة — البحث في نص التفسير يتوسع تدريجيًا مع اكتمال التفريغ الآلي للمقاطع."
        />
      </section>
    </main>
  );
}
