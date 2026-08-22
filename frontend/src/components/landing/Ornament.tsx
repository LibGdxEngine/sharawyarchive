/**
 * Ornamental divider — a hairline gold rule with an eight-point star medallion
 * at its centre, the classic Quran-manuscript chapter header. Decorative only.
 */
export default function Ornament({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`flex items-center gap-4 ${className}`}
      role="presentation"
    >
      <span className="h-px flex-1 bg-[var(--landing-pattern-faint)]" />
      <svg
        width="26"
        height="26"
        viewBox="0 0 26 26"
        fill="none"
        className="shrink-0 text-[var(--landing-gold)]"
      >
        <rect
          x="6.5"
          y="6.5"
          width="13"
          height="13"
          stroke="currentColor"
          strokeWidth="1.2"
        />
        <rect
          x="6.5"
          y="6.5"
          width="13"
          height="13"
          stroke="currentColor"
          strokeWidth="1.2"
          transform="rotate(45 13 13)"
        />
        <circle cx="13" cy="13" r="2" fill="currentColor" />
      </svg>
      <span className="h-px flex-1 bg-[var(--landing-pattern-faint)]" />
    </div>
  );
}
