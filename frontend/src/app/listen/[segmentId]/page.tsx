import type { Metadata } from "next";
import { notFound } from "next/navigation";
import ErrorNote from "@/components/ErrorNote";
import SiteHeader from "@/components/SiteHeader";
import Player from "@/components/player/Player";
import { getSegment, getTranscript } from "@/lib/api";
import { kindLabel } from "@/lib/format";
import { SITE_NAME } from "@/lib/site";
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

/** "الآية 5" for a single ayah, "الآيات 5–9" for a span. */
function ayahRangeLabel(start: number, end: number): string {
  return start === end ? `الآية ${start}` : `الآيات ${start}–${end}`;
}

export async function generateMetadata({
  params,
}: ListenPageProps): Promise<Metadata> {
  const { segmentId } = await params;
  const id = Number.parseInt(segmentId, 10);

  // The API can be down at build or request time; metadata must never be the
  // reason a page fails to render, so every failure falls back to the static
  // site-level description.
  const fallback: Metadata = {
    title: `مقطع صوتي — ${SITE_NAME}`,
    alternates: { canonical: `/listen/${segmentId}` },
  };
  if (!Number.isInteger(id) || id <= 0) return fallback;

  let segment: Segment;
  try {
    segment = await getSegment(id);
  } catch {
    return fallback;
  }

  const title = `${segment.title} — ${SITE_NAME}`;
  const description = `${kindLabel(segment.kind)} · سورة ${segment.surah} · ${ayahRangeLabel(
    segment.ayah_start,
    segment.ayah_end
  )} — من أرشيف الشيخ محمد متولي الشعراوي الصوتي`;

  return {
    title,
    description,
    alternates: { canonical: `/listen/${id}` },
    openGraph: {
      type: "music.song",
      siteName: SITE_NAME,
      locale: "ar_AR",
      title,
      description,
      url: `/listen/${id}`,
      duration: Math.round(segment.duration_ms / 1000),
      ...(segment.audio_url
        ? { audio: [{ url: segment.audio_url }] }
        : {}),
    },
  };
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
