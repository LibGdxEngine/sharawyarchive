import Link from "next/link";
import ChunkResultList from "@/components/ChunkResultList";
import ErrorNote from "@/components/ErrorNote";
import { AyahSeal, OrnamentDivider } from "@/components/surah/SurahOrnaments";
import { search } from "@/lib/api";
import { kindLabel, toArabicIndic } from "@/lib/format";
import type { AyahMatch, SearchResponse, VerseMatch } from "@/types/models";

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

/*
  One verse hit — the whole card is the link. It goes straight to the ayah's
  listen page (`/surah/[n]/ayah/[m]`), where the covering segment plays.
*/
function VerseHit({
  verse,
  index,
}: {
  verse: AyahMatch | VerseMatch;
  index: number;
}) {
  const meta = [`سورة ${verse.surah_name_ar}`];
  if ("juz" in verse) {
    meta.push(`الجزء ${toArabicIndic(verse.juz)}`, `صفحة ${toArabicIndic(verse.page)}`);
  }
  return (
    <li>
      <Link
        href={`/surah/${verse.surah}/ayah/${verse.number}`}
        className="search-hit group"
        style={{ animationDelay: `${150 + Math.min(index, 12) * 60}ms` }}
      >
        <div className="flex gap-3 sm:gap-4">
          <AyahSeal number={verse.number} />
          <div className="min-w-0 flex-1">
            <p className="search-hit-text quran-text text-2xl">
              {verse.text_uthmani}{" "}
              <span className="search-hit-mark text-lg">
                ﴿{toArabicIndic(verse.number)}﴾
              </span>
            </p>
            <span className="mt-2 flex items-center gap-1.5 text-xs">
              <span className="search-hit-meta">{meta.join(" · ")}</span>
              <svg
                aria-hidden
                className="search-hit-chevron"
                width="14"
                height="14"
                viewBox="0 0 14 14"
                fill="none"
              >
                <path
                  d="M9 3 5 7l4 4"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </span>
          </div>
        </div>
      </Link>
    </li>
  );
}

function summaryLine(response: SearchResponse): string {
  const ayahCount = response.ayah_matches.length + response.verse_matches.length;
  const parts: string[] = [];
  if (ayahCount > 0) parts.push(`${ayahCount} آية مطابقة`);
  if (response.total > 0) parts.push(`${response.total} مقطعًا من الأرشيف`);
  return parts.length > 0 ? parts.join(" · ") : "لا نتائج";
}

export default async function SearchPage({ searchParams }: SearchPageProps) {
  const params = await searchParams;
  const query = firstValue(params.q).trim();
  const kind = firstKind(params.kind);

  if (query === "") {
    return (
      <main className="search-page reading-column page-shell pt-8">
        <div className="pt-10 text-center">
          <OrnamentDivider className="mx-auto max-w-40" />
          <p className="mt-6 text-sm text-[var(--color-ink-muted)]">
            اكتب عبارة في حقل البحث للبدء.
          </p>
        </div>
      </main>
    );
  }

  let response: SearchResponse;
  try {
    response = await search({ q: query, kind });
  } catch {
    return (
      <main className="search-page reading-column page-shell pt-8">
        <ErrorNote />
      </main>
    );
  }

  const hasQuranSection =
    response.ayah_matches.length > 0 || response.verse_matches.length > 0;
  const hasAnyResult = hasQuranSection || response.results.length > 0;
  // تلاوة searches canonical mushaf text only — no ASR transcript section.
  const showTranscripts = kind !== "recitation";

  return (
    <main className="search-page reading-column page-shell pt-8">
      <header className="search-hero">
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
          {summaryLine(response)}
        </p>
        <div aria-hidden className="search-hero-rule mt-3" />
      </header>

      {!hasAnyResult ? (
        <div className="pt-12 text-center">
          <OrnamentDivider className="mx-auto max-w-40" />
          <p className="mt-6 text-sm text-[var(--color-ink-muted)]">
            {kind === "recitation"
              ? "جرّب عبارة أقصر أو صيغة أخرى — البحث يغطي نص المصحف فقط."
              : kind === "khawatir"
                ? "جرّب عبارة أقصر أو صيغة أخرى — البحث يغطي تفريغ المقاطع آليًا."
                : "جرّب عبارة أقصر أو صيغة أخرى — البحث يشمل نص المصحف وتفريغ المقاطع."}
          </p>
        </div>
      ) : null}

      {response.ayah_matches.length > 0 ? (
        <section className="search-section mt-8" style={{ animationDelay: "100ms" }}>
          <h2 className="flex items-center gap-2 text-xs text-[var(--color-ink-muted)]">
            آيات مطابقة
            <span className="sp-badge sp-badge--gold">من القرآن الكريم</span>
          </h2>
          <ul className="mt-2 space-y-1">
            {response.ayah_matches.map((ayah, i) => (
              <VerseHit key={`${ayah.surah}:${ayah.number}`} verse={ayah} index={i} />
            ))}
          </ul>
        </section>
      ) : null}

      {response.verse_matches.length > 0 ? (
        <section className="search-section mt-8" style={{ animationDelay: "140ms" }}>
          <h2 className="flex items-center gap-2 text-xs text-[var(--color-ink-muted)]">
            بحث نصّي في المصحف
            <span className="sp-badge sp-badge--gold">نص المصحف</span>
          </h2>
          <ul className="mt-2 space-y-1">
            {response.verse_matches.map((verse, i) => (
              <VerseHit
                key={`${verse.surah}:${verse.number}`}
                verse={verse}
                index={response.ayah_matches.length + i}
              />
            ))}
          </ul>
        </section>
      ) : null}

      {/*
        Two kinds of text share this page and they must never read as one
        list: everything above the ornament divider is the mushaf, everything
        below it is what the recogniser heard. The divider carries that rule
        visually; the labels make it explicit.
      */}
      {hasQuranSection && showTranscripts ? (
        <OrnamentDivider className="mx-auto mt-10 max-w-52" />
      ) : null}

      {hasAnyResult && showTranscripts ? (
        <section className="search-section mt-8" style={{ animationDelay: "200ms" }}>
          <h2 className="text-xs text-[var(--color-ink-muted)]">
            مقاطع من الأرشيف — تفريغ آلي
          </h2>
          <ChunkResultList
            results={response.results}
            emptyLabel="لا توجد مقاطع مطابقة لهذه العبارة — البحث في نص التفسير يتوسع تدريجيًا مع اكتمال التفريغ الآلي للمقاطع."
          />
        </section>
      ) : null}
    </main>
  );
}
