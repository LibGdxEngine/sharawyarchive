import Link from "next/link";
import { Suspense } from "react";

import { amiriFont, brandFont } from "@/fonts";
import IslamicPattern from "@/components/landing/IslamicPattern";
import Ornament from "@/components/landing/Ornament";
import SearchHero from "@/components/landing/SearchHero";
import ContentDiscovery from "@/components/landing/ContentDiscovery";

/*
 * Landing page — rewritten as an Islamic manuscript-inspired composition:
 * a bismillah header, a gold eight-pointed-star lattice ground, and the
 * search box nested in a mihrab niche. Still the scoped brand exception
 * documented in DESIGN.md — gold + deep-emerald palette only on this route.
 */

/* Symmetric waveform — the brand mark. Bar heights straight from the mockup. */
const LOGO_BARS = [6, 12, 20, 28, 38, 50, 62, 50, 38, 28, 20, 12, 6];

function Waveform({
  heights,
  animate = false,
}: {
  heights: number[];
  animate?: boolean;
}) {
  return (
    <div
      className={
        animate
          ? "waveform-entrance flex items-end gap-[3px]"
          : "flex items-end gap-[3px]"
      }
    >
      {heights.map((height, i) => (
        <span
          key={i}
          className="w-[4px] rounded-[2px] bg-[var(--landing-gold)]"
          style={{
            height,
            animationDelay: animate ? `${i * 30}ms` : undefined,
          }}
        />
      ))}
    </div>
  );
}

export default function HomePage() {
  return (
    <main
      className={`${brandFont.variable} ${amiriFont.variable} landing page-shell relative overflow-hidden bg-[var(--landing-bg)] text-[var(--landing-ink)]`}
    >
      {/* Geometric lattice ground — faint, behind everything. */}
      <div
        aria-hidden
        className="landing-pattern pointer-events-none absolute inset-0 opacity-[0.05]"
      >
        <IslamicPattern />
      </div>

      {/* Hero section — fills viewport, search-focused */}
      <section className="relative flex min-h-screen flex-col items-center justify-center px-6 py-12">
        <div className="relative flex w-full max-w-[760px] flex-col items-center text-center">
          <p className="landing-rise quran-text text-2xl leading-[2] text-[var(--landing-gold)]">
            بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ
          </p>

          <div aria-hidden className="landing-rise mt-6 h-[54px]">
            <Waveform heights={LOGO_BARS} animate />
          </div>

          <h1 className="landing-rise mt-3 text-6xl font-semibold leading-[1.15] [font-family:var(--font-brand)] text-[var(--landing-emerald-ink)]">
            أرشيف الشعراوي
          </h1>
          <p className="landing-rise mt-2 text-sm font-medium tracking-wide text-[var(--landing-gold)] [font-family:var(--font-brand)]">
            تلاوات وخواطر الشيخ محمد متولي الشعراوي
          </p>

          <Ornament className="landing-rise mt-6 w-full max-w-[340px]" />

          <p className="landing-rise mt-5 text-xl font-normal leading-[1.9] text-balance text-[var(--landing-ink-2)] [font-family:var(--font-amiri)]">
            ابحث في التلاوة والتفسير — واستمع من اللحظة التي قيلت فيها الكلمة
          </p>

          {/* The mihrab niche holding the search hero */}
          <div className="landing-rise relative z-10 mt-10 w-full">
            <div
              aria-hidden
              className="landing-halo pointer-events-none absolute -inset-x-6 -bottom-10 -top-8 rounded-[44px]"
            />
            <div
              aria-hidden
              className="relative mx-auto -mb-1 h-12 w-24 text-[var(--landing-gold)]"
            >
              <svg viewBox="0 0 96 56" fill="none" className="h-full w-full">
                <path
                  d="M10 54 C 10 26 34 10 48 6 C 62 10 86 26 86 54"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  vectorEffect="non-scaling-stroke"
                />
                <rect
                  x="42"
                  y="4"
                  width="12"
                  height="12"
                  stroke="currentColor"
                  strokeWidth="1.2"
                  transform="rotate(45 48 10)"
                />
              </svg>
            </div>
            <div className="relative">
              <SearchHero />
            </div>
          </div>

          <nav
            aria-label="أقسام الأرشيف"
            className="landing-rise mt-8 flex flex-wrap items-center justify-center gap-3"
          >
            <Link
              href="/surahs"
              className="rounded-xl border border-[var(--landing-chip-border)] bg-[var(--landing-chip-bg)] px-7 py-3 text-sm font-medium text-[var(--landing-ink-3)] transition-colors hover:border-[var(--landing-gold-focus)] hover:text-[var(--landing-chip-ink-hover)]"
            >
              فهرس السور
            </Link>
          </nav>
        </div>

        <p className="mt-auto pt-8 text-center text-[13px] text-[var(--landing-ink-4)]">
          النصوص القرآنية من مصادر موثّقة — تنزيل وQUL · النسخ الآلي للخواطر
          مُعلَّم بوضوح
        </p>
      </section>

      {/* Content discovery — below the fold */}
      <Suspense fallback={null}>
        <section className="flex flex-col items-center px-6">
          <ContentDiscovery />
        </section>
      </Suspense>
    </main>
  );
}
