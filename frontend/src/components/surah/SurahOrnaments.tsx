import { toArabicIndic } from "@/lib/format";

/**
 * Decorative ornaments for the /surah/[n] "mushaf illumination" exception
 * (DESIGN.md). Everything here is decorative chrome — every SVG is
 * aria-hidden and all colours come from the `.surah-page` token scope in
 * globals.css. Server components: no client JS is shipped for them.
 */

/**
 * Star lattice band crowning (and footing) the surah hero. A single tile
 * holds one full eight-point star at each corner and one at the tile centre
 * (body-centred grid), so the pattern repeats seamlessly; `currentColor`
 * stroked, tinted and masked by `.surah-hero-lattice`.
 */
export function HeroLattice({ flip = false }: { flip?: boolean }) {
  return (
    <svg
      aria-hidden
      role="presentation"
      preserveAspectRatio="xMidYMin slice"
      viewBox="0 0 336 48"
      className={`surah-hero-lattice${flip ? " surah-hero-lattice--bottom" : ""}`}
    >
      <defs>
        <g id="sp-star8">
          <rect x="-11" y="-11" width="22" height="22" />
          <rect
            x="-11"
            y="-11"
            width="22"
            height="22"
            transform="rotate(45)"
          />
          <circle r="3" />
        </g>
        <pattern
          id="sp-girih"
          width="42"
          height="42"
          patternUnits="userSpaceOnUse"
        >
          <g fill="none" stroke="currentColor" strokeWidth="1">
            <use href="#sp-star8" transform="translate(0 0)" />
            <use href="#sp-star8" transform="translate(42 0)" />
            <use href="#sp-star8" transform="translate(0 42)" />
            <use href="#sp-star8" transform="translate(42 42)" />
            <use href="#sp-star8" transform="translate(21 21)" />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#sp-girih)" />
    </svg>
  );
}

/** One mushaf-margin corner flourish (double arc + endpoint dots). */
function CornerSvg() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden>
      <path d="M23 1 H9 Q1 1 1 9 V23" strokeWidth="1.4" />
      <path
        d="M23 5.5 H10 Q5.5 5.5 5.5 10 V23"
        strokeWidth="1.4"
        opacity="0.5"
      />
      <circle cx="23" cy="1" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="1" cy="23" r="1.3" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** The four corner flourishes, mirrored into each corner of the hero panel. */
export function HeroCorners() {
  return (
    <>
      <span aria-hidden className="surah-hero-corner end-3 top-3">
        <CornerSvg />
      </span>
      <span aria-hidden className="surah-hero-corner start-3 top-3 -scale-x-100">
        <CornerSvg />
      </span>
      <span aria-hidden className="surah-hero-corner bottom-3 end-3 -scale-y-100">
        <CornerSvg />
      </span>
      <span aria-hidden className="surah-hero-corner bottom-3 start-3 scale-[-1]">
        <CornerSvg />
      </span>
    </>
  );
}

/**
 * Ornamental divider — a hairline gold rule with an eight-point star
 * medallion at its centre, the classic chapter-header vignette.
 */
export function OrnamentDivider({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      role="presentation"
      className={`flex items-center gap-4 ${className}`}
    >
      <span className="sp-rule" />
      <svg
        width="22"
        height="22"
        viewBox="0 0 26 26"
        fill="none"
        className="shrink-0 text-[var(--sp-gold)]"
      >
        <rect
          x="6.5"
          y="6.5"
          width="13"
          height="13"
          stroke="currentColor"
          strokeWidth="1.1"
        />
        <rect
          x="6.5"
          y="6.5"
          width="13"
          height="13"
          stroke="currentColor"
          strokeWidth="1.1"
          transform="rotate(45 13 13)"
        />
        <circle cx="13" cy="13" r="2" fill="currentColor" />
      </svg>
      <span className="sp-rule sp-rule--mirror" />
    </div>
  );
}

/**
 * The rosette verse seal — concentric circles with a dotted outer ring and
 * the Arabic-Indic ayah number at the centre, drawn like a mushaf verse
 * marker. `.surah-ayah` hover/active states light the seal up from CSS.
 */
export function AyahSeal({ number }: { number: number }) {
  return (
    <span aria-hidden className="ayah-seal">
      <svg viewBox="0 0 48 48">
        <circle className="seal-body" cx="24" cy="24" r="13.5" />
        <circle className="seal-outer" cx="24" cy="24" r="21.5" />
        <circle className="seal-inner" cx="24" cy="24" r="17" />
        <g className="seal-dots">
          <circle cx="43" cy="24" r="1.1" />
          <circle cx="37.44" cy="37.44" r="1.1" />
          <circle cx="24" cy="43" r="1.1" />
          <circle cx="10.56" cy="37.44" r="1.1" />
          <circle cx="5" cy="24" r="1.1" />
          <circle cx="10.56" cy="10.56" r="1.1" />
          <circle cx="24" cy="5" r="1.1" />
          <circle cx="37.44" cy="10.56" r="1.1" />
        </g>
      </svg>
      <span className="ayah-seal-num">{toArabicIndic(number)}</span>
    </span>
  );
}
