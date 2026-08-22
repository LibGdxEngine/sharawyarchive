import Link from "next/link";
import { getSurahs, getTopics } from "@/lib/api";
import { toArabicIndic } from "@/lib/format";
import Ornament from "./Ornament";
import ContinueListening from "./ContinueListening";

const FEATURED_SURAH_NUMBERS = [1, 36, 18, 56, 55, 67, 78, 112];
const FEATURED_TOPIC_SLUGS = [
  "alrizq-waltwkl",
  "alrhmh",
  "alstwbh",
];

/**
 * Eight-pointed star medallion with the surah number nested inside, rendered
 * as two rotated squares behind an absolutely-centred figure.
 */
function SurahMedallion({ number }: { number: number }) {
  return (
    <div
      aria-hidden
      className="relative mx-auto flex h-14 w-14 items-center justify-center"
    >
      <svg
        viewBox="0 0 56 56"
        className="absolute inset-0 h-full w-full text-[var(--landing-gold)]"
        fill="none"
      >
        <rect
          x="12"
          y="12"
          width="32"
          height="32"
          stroke="currentColor"
          strokeWidth="1.4"
        />
        <rect
          x="12"
          y="12"
          width="32"
          height="32"
          stroke="currentColor"
          strokeWidth="1.4"
          transform="rotate(45 28 28)"
        />
      </svg>
      <span className="relative text-sm font-semibold text-[var(--landing-emerald-ink)]">
        {toArabicIndic(number)}
      </span>
    </div>
  );
}

export default async function ContentDiscovery() {
  let surahs = null;
  let topics = null;
  try {
    [surahs, topics] = await Promise.all([getSurahs(), getTopics()]);
  } catch {
    return null;
  }

  const featuredSurahs = surahs.filter((s) =>
    FEATURED_SURAH_NUMBERS.includes(s.number),
  );
  const featuredTopics = topics.filter((t) =>
    FEATURED_TOPIC_SLUGS.includes(t.slug),
  );

  const totalSegments = surahs.reduce((sum, s) => sum + s.segment_count, 0);
  const totalAyahs = surahs.reduce((sum, s) => sum + s.ayah_count, 0);

  return (
    <div className="mt-16 flex w-full max-w-[760px] flex-col items-center pb-16">
      <Ornament className="w-full max-w-[340px]" />

      <section className="mt-10 w-full">
        <h2 className="text-center text-base font-semibold text-[var(--landing-emerald-ink)] [font-family:var(--font-brand)]">
          سور مضيئة
        </h2>
        <p className="mt-1 text-center text-xs text-[var(--landing-ink-4)]">
          ابدأ من تلاوة كاملة أو تفسير سورة
        </p>

        <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {featuredSurahs.map((surah) => (
            <Link
              key={surah.number}
              href={`/surah/${surah.number}`}
              className="rounded-2xl border border-[var(--landing-chip-border)] bg-[var(--landing-chip-bg)] px-3 py-5 text-center transition-colors hover:border-[var(--landing-gold-focus)]"
            >
              <SurahMedallion number={surah.number} />
              <div className="quran-text mt-3 text-lg leading-normal text-[var(--landing-ink)]">
                {surah.name_ar}
              </div>
              <div className="mt-1 text-[11px] text-[var(--landing-ink-4)]">
                {toArabicIndic(surah.ayah_count)} آية
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section className="mt-12 w-full">
        <h2 className="text-center text-base font-semibold text-[var(--landing-emerald-ink)] [font-family:var(--font-brand)]">
          موضوعات من الخواطر
        </h2>
        <div className="mt-5 flex flex-wrap justify-center gap-2.5">
          {featuredTopics.map((topic) => (
            <Link
              key={topic.slug}
              href={`/topics/${topic.slug}`}
              className="rounded-full border border-[var(--landing-chip-border)] bg-[var(--landing-chip-bg)] px-5 py-2.5 text-sm text-[var(--landing-ink-3)] transition-colors hover:border-[var(--landing-gold-focus)] hover:text-[var(--landing-chip-ink-hover)]"
            >
              {topic.name_ar}
            </Link>
          ))}
          <Link
            href="/topics"
            className="rounded-full border border-dashed border-[var(--landing-gold-focus)] bg-transparent px-5 py-2.5 text-sm text-[var(--landing-ink-4)] transition-colors hover:border-[var(--landing-gold)] hover:text-[var(--landing-chip-ink-hover)]"
          >
            كل الموضوعات ←
          </Link>
        </div>
      </section>

      <ContinueListening />

      {/* Archive figures — deep emerald closing band */}
      <div className="mt-12 w-full rounded-2xl bg-[var(--landing-emerald)] px-6 py-6">
        <div className="flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-[#e9e0c8]">
          <span className="flex items-baseline gap-2">
            <span className="text-xl font-semibold [font-family:var(--font-brand)]">
              {toArabicIndic(surahs.length)}
            </span>
            سورة
          </span>
          <span className="flex items-baseline gap-2">
            <span className="text-xl font-semibold [font-family:var(--font-brand)]">
              {toArabicIndic(totalAyahs)}
            </span>
            آية
          </span>
          <span className="flex items-baseline gap-2">
            <span className="text-xl font-semibold [font-family:var(--font-brand)]">
              {toArabicIndic(totalSegments)}
            </span>
            مقطع صوتي
          </span>
          <span className="flex items-baseline gap-2">
            <span className="text-xl font-semibold [font-family:var(--font-brand)]">
              {toArabicIndic(topics.length)}
            </span>
            موضوع
          </span>
        </div>
      </div>
    </div>
  );
}
