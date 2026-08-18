import { notFound } from "next/navigation";
import ErrorNote from "@/components/ErrorNote";
import SiteHeader from "@/components/SiteHeader";
import Player from "@/components/player/Player";
import { getSegment, getTranscript } from "@/lib/api";
import type { Segment, Transcript } from "@/types/models";

// Segment metadata carries a presigned, expiring audio URL and the transcript
// is fetched per request, so this route is never prerendered.
export const dynamic = "force-dynamic";

interface ListenPageProps {
  params: Promise<{ segmentId: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

/** `?t=<ms>` deep-link position, or null when absent or malformed. */
function parseStartMs(raw: string | string[] | undefined): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined) return null;
  const ms = Number.parseInt(value, 10);
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

export default async function ListenPage({
  params,
  searchParams,
}: ListenPageProps) {
  const { segmentId } = await params;
  const id = Number.parseInt(segmentId, 10);
  if (!Number.isInteger(id) || id <= 0) notFound();

  const startMs = parseStartMs((await searchParams).t);

  let segment: Segment;
  let transcript: Transcript;
  try {
    segment = await getSegment(id);
    transcript = await getTranscript(id, segment.transcript_version);
  } catch {
    return (
      <>
        <SiteHeader />
        <main className="reading-column page-shell">
          <ErrorNote>تعذّر تحميل هذا المقطع الآن. حاول مرة أخرى بعد قليل.</ErrorNote>
        </main>
      </>
    );
  }

  return (
    <>
      <SiteHeader />
      <main>
        <Player segment={segment} transcript={transcript} startMs={startMs} />
      </main>
    </>
  );
}
