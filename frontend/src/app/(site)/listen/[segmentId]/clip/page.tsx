import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { amiriFont } from "@/fonts";
import { SITE_NAME } from "@/lib/site";
import ClipPageClient from "./ClipPageClient";

// The composer fetches the segment client-side (same reasoning as the listen
// page: presigned URLs and the service-worker cache), so this shell is never
// prerendered.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: `مقطع للمشاركة — ${SITE_NAME}`,
  description:
    "اقتطع أي جزء من المقطع — من ثانية واحدة حتى نهايته — وأنشئ فيديو بنصٍّ كاريوكي وموجة صوتية متحركة، أو نزّل الصوت وحده مع نصّه.",
};

interface ClipPageProps {
  params: Promise<{ segmentId: string }>;
}

export default async function ClipPage({ params }: ClipPageProps) {
  const { segmentId } = await params;
  const id = Number.parseInt(segmentId, 10);

  if (!Number.isInteger(id) || id <= 0) notFound();

  return (
    // `.listen-page` is the scoped brand exception (see globals.css); the clip
    // composer reuses the same gold tokens, so the page joins that scope.
    <main className={`listen-page ${amiriFont.variable}`}>
      <div className="reading-column page-shell pt-8">
        <ClipPageClient segmentId={id} />
      </div>
    </main>
  );
}
