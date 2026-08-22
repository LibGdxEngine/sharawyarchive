import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { amiriFont } from "@/fonts";
import { getSegment } from "@/lib/api";
import { kindLabel } from "@/lib/format";
import { SITE_NAME } from "@/lib/site";
import type { Segment } from "@/types/models";
import ListenClient from "./ListenClient";

// generateMetadata reads a presigned, expiring audio URL, so this route is
// never prerendered. The page body itself no longer fetches: the segment and
// its transcript are loaded in the browser (see ListenClient) so that the
// service worker caches them and a saved segment still opens offline.
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

  return (
    // `.listen-page` is the route's scoped brand exception (see globals.css) —
    // server-rendered so the gold tokens never flash in; `amiriFont.variable`
    // loads the classical face for the hero title on this route alone.
    <main className={`listen-page ${amiriFont.variable}`}>
      <ListenClient segmentId={id} startMs={startMs} />
    </main>
  );
}
