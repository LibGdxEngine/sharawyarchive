export default function HomePage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4">
      <h1 className="text-3xl font-semibold mb-8">أرشيف الشعراوي</h1>
      <form action="/search" method="GET" className="w-full max-w-md">
        <label htmlFor="q" className="sr-only">
          بحث في الخواطر
        </label>
        <input
          id="q"
          name="q"
          type="search"
          placeholder="ابحث في الخواطر…"
          autoComplete="off"
          className="w-full border border-[var(--color-border)] rounded px-4 py-3 text-base bg-[var(--color-surface)] text-[var(--color-ink)] placeholder:text-[var(--color-ink-faint)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]"
        />
        <button
          type="submit"
          className="mt-3 w-full py-2 px-4 rounded bg-[var(--color-accent)] text-white font-medium"
        >
          بحث
        </button>
      </form>
    </main>
  );
}
