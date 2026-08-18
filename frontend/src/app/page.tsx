import Link from "next/link";

/**
 * Landing page: the search field is the hero. One centred column, the title in
 * the Quranic face, the input, a few example queries. Nothing else — no cards,
 * no shadows, no gradients (DESIGN.md, "Restraint").
 */

const EXAMPLES = [
  "الصبر",
  "آية الكرسي",
  "الرزق من عند الله",
  "البقرة 255",
];

export default function HomePage() {
  return (
    <main className="reading-column page-shell flex min-h-screen flex-col justify-center py-16">
      <h1 className="quran-text text-center text-4xl">أرشيف الشعراوي</h1>
      <p className="mt-3 text-center text-sm text-[var(--color-ink-muted)]">
        ابحث عن أي عبارة، وانتقل مباشرةً إلى لحظة قولها.
      </p>

      <form action="/search" method="GET" className="mt-10">
        <label htmlFor="site-search" className="sr-only">
          ابحث في الأرشيف
        </label>
        <input
          id="site-search"
          name="q"
          type="search"
          placeholder="ابحث في الأرشيف…"
          autoComplete="off"
          autoFocus
          className="w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-4 text-base placeholder:text-[var(--color-ink-faint)]"
        />
      </form>

      <ul className="mt-6 flex flex-wrap justify-center gap-x-5 gap-y-2">
        {EXAMPLES.map((example) => (
          <li key={example}>
            <Link
              href={`/search?q=${encodeURIComponent(example)}`}
              className="text-sm text-[var(--color-ink-muted)]"
            >
              {example}
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
