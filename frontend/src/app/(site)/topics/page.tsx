import Link from "next/link";
import ErrorNote from "@/components/ErrorNote";
import { getTopics } from "@/lib/api";
import type { Topic } from "@/types/models";

export const dynamic = "force-dynamic";

export default async function TopicsPage() {
  let topics: Topic[];
  try {
    topics = await getTopics();
  } catch {
    return (
      <main className="reading-column page-shell pt-8">
        <ErrorNote />
      </main>
    );
  }

  return (
    <main className="reading-column page-shell pt-8">
      <h1 className="text-lg font-semibold">الموضوعات</h1>

      {topics.length === 0 ? (
        <p className="py-8 text-sm text-[var(--color-ink-muted)]">
          لا توجد موضوعات منشورة بعد.
        </p>
      ) : (
        <ul className="mt-6 divide-y divide-[var(--color-border-subtle)]">
          {topics.map((topic) => (
            <li key={topic.slug} className="py-4">
              <Link href={`/topics/${topic.slug}`} className="text-base">
                {topic.name_ar}
              </Link>
              <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
                {topic.chunk_count} مقطع
              </p>
              {topic.description_ar ? (
                <p className="mt-1 text-sm text-[var(--color-ink-muted)]">
                  {topic.description_ar}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
