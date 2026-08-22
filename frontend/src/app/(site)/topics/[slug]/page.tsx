import ChunkResultList from "@/components/ChunkResultList";
import ErrorNote from "@/components/ErrorNote";
import { getTopic } from "@/lib/api";
import type { TopicDetail } from "@/types/models";

export const dynamic = "force-dynamic";

interface TopicPageProps {
  params: Promise<{ slug: string }>;
}

export default async function TopicPage({ params }: TopicPageProps) {
  const { slug } = await params;

  let topic: TopicDetail;
  try {
    topic = await getTopic(slug);
  } catch {
    return (
      <main className="reading-column page-shell pt-8">
        <ErrorNote />
      </main>
    );
  }

  return (
    <main className="reading-column page-shell pt-8">
      <h1 className="text-lg font-semibold">{topic.name_ar}</h1>
      {topic.description_ar ? (
        <p className="mt-1 text-sm text-[var(--color-ink-muted)]">
          {topic.description_ar}
        </p>
      ) : null}

      <ChunkResultList
        results={topic.chunks}
        emptyLabel="لا توجد مقاطع في هذا الموضوع بعد."
      />
    </main>
  );
}
