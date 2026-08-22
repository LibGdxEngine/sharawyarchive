/**
 * Seamless eight-pointed star lattice — the brand's geometric ground.
 *
 * A single tile holds one full star on each corner and one at the tile centre
 * (a body-centred grid), so the SVG `<pattern>` repeats without a visible
 * seam. Everything is stroked with `currentColor`; set the colour through
 * `.landing-pattern` (see globals.css) or a Tailwind `text-*` utility on the
 * wrapper. Decorative only: always rendered `aria-hidden`.
 */
export default function IslamicPattern() {
  return (
    <svg
      aria-hidden
      className="h-full w-full"
      width="100%"
      height="100%"
      role="presentation"
    >
      <defs>
        <g id="landing-star8">
          <rect x="-16" y="-16" width="32" height="32" />
          <rect
            x="-16"
            y="-16"
            width="32"
            height="32"
            transform="rotate(45)"
          />
          <circle r="4.5" />
        </g>
        <pattern
          id="landing-girih"
          width="112"
          height="112"
          patternUnits="userSpaceOnUse"
        >
          <g fill="none" stroke="currentColor" strokeWidth="1">
            <use href="#landing-star8" transform="translate(0 0)" />
            <use href="#landing-star8" transform="translate(112 0)" />
            <use href="#landing-star8" transform="translate(0 112)" />
            <use href="#landing-star8" transform="translate(112 112)" />
            <use href="#landing-star8" transform="translate(56 56)" />
          </g>
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#landing-girih)" />
    </svg>
  );
}
