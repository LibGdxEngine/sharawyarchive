import { cache } from "react";
import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { amiriFont } from "@/fonts";
import { getSegment, getTranscript } from "@/lib/api";
import { kindLabel } from "@/lib/format";
import { SITE_NAME } from "@/lib/site";
import type { Segment, Transcript } from "@/types/models";
import ListenClient from "./ListenClient";

// generateMetadata reads a presigned, expiring audio URL, so this route is
// never prerendered.
//
// The segment and transcript are fetched here *and* in the browser. The server
// copy is what the first paint renders, so opening a segment costs no client
// round trip; the browser then refetches (see `useSegmentData`) because only a
// request a client makes itself lands in the service worker's cache, and
// because a document replayed from that cache carries an audio URL whose six
// hours may well have run out.
export const dynamic = "force-dynamic";

/**
 * Deduplicates the segment fetch between `generateMetadata` and the render —
 * the same trick `surah/[n]` uses for `loadSurah`. Both ask for the same id,
 * so the two calls collapse into one request to the API.
 */
const loadSegment = cache((id: number): Promise<Segment> => getSegment(id));

/**
 * The segment plus its transcript, or nulls where the API could not answer.
 *
 * Never throws: a segment that fails to load server-side has to reach
 * `ListenClient` anyway, because the copy saved for offline reading lives in
 * the browser and is the only thing that can answer when the API cannot.
 */
async function loadInitialData(
  id: number
): Promise<{ segment: Segment | null; transcript: Transcript | null }> {
  let segment: Segment;
  try {
    segment = await loadSegment(id);
  } catch {
    return { segment: null, transcript: null };
  }
  if (segment.transcript_version === null) {
    // Ingested but not yet transcribed: playable, honestly untranscribed.
    return { segment, transcript: null };
  }
  try {
    return {
      segment,
      transcript: await getTranscript(id, segment.transcript_version, {
        store: false,
      }),
    };
  } catch {
    // The player is still worth rendering without its transcript pane.
    return { segment, transcript: null };
  }
}

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
    segment = await loadSegment(id);
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

  // Both are already in flight from generateMetadata's `loadSegment`, so the
  // await costs one API round trip for the page, not two.
  const [startMs, initial] = await Promise.all([
    searchParams.then((query) => parseStartMs(query.t)),
    loadInitialData(id),
  ]);

  return (
    // `.listen-page` is the route's scoped brand exception (see globals.css) —
    // server-rendered so the gold tokens never flash in; `amiriFont.variable`
    // loads the classical face for the hero title on this route alone.
    <main className={`listen-page ${amiriFont.variable}`}>
      <ListenClient
        segmentId={id}
        startMs={startMs}
        initialSegment={initial.segment}
        initialTranscript={initial.transcript}
      />
    </main>
  );
}
