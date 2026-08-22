import type { Metadata } from "next";
import Link from "next/link";
import ErrorNote from "@/components/ErrorNote";
import { getClip } from "@/lib/api";
import { SITE_NAME, SITE_URL, siteHost } from "@/lib/site";
import type { Clip } from "@/types/models";

// The clip render finishes asynchronously and video_url is presigned, so this
// page is never prerendered or cached.
export const dynamic = "force-dynamic";

interface ClipPageProps {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

const TITLE = `مقطع من ${SITE_NAME}`;
const DESCRIPTION =
  "مقطع مقتطع من خواطر الشيخ محمد متولي الشعراوي — من الأرشيف الصوتي القابل للبحث";

const STATUS_TEXT: Record<Clip["status"], string> = {
  queued: "المقطع في قائمة الانتظار…",
  rendering: "جارٍ إنشاء المقطع — حدّث الصفحة بعد قليل.",
  done: "المقطع جاهز",
  failed: "تعذّر إنشاء هذا المقطع.",
};

/** `?segment=<id>` written by the composer, so the share page can link home. */
function parseSegmentId(raw: string | string[] | undefined): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined) return null;
  const id = Number.parseInt(value, 10);
  return Number.isInteger(id) && id > 0 ? id : null;
}

export async function generateMetadata({
  params,
}: ClipPageProps): Promise<Metadata> {
  const { id } = await params;
  const fallback: Metadata = {
    title: TITLE,
    description: DESCRIPTION,
    alternates: { canonical: `/clip/${id}` },
  };

  let clip: Clip;
  try {
    clip = await getClip(id);
  } catch {
    return fallback;
  }

  if (clip.video_url === null) return fallback;

  return {
    ...fallback,
    openGraph: {
      type: "video.other",
      siteName: SITE_NAME,
      locale: "ar_AR",
      title: TITLE,
      description: DESCRIPTION,
      url: `/clip/${id}`,
      videos: [{ url: clip.video_url, type: "video/mp4" }],
    },
    twitter: {
      card: "player",
      title: TITLE,
      description: DESCRIPTION,
      players: [
        {
          playerUrl: `${SITE_URL}/clip/${id}`,
          streamUrl: clip.video_url,
          width: 1080,
          height: 1920,
        },
      ],
    },
  };
}

export default async function ClipPage({
  params,
  searchParams,
}: ClipPageProps) {
  const { id } = await params;
  const segmentId = parseSegmentId((await searchParams).segment);

  let clip: Clip;
  try {
    clip = await getClip(id);
  } catch {
    return (
      <main className="reading-column page-shell pt-8">
        <ErrorNote>
          تعذّر العثور على هذا المقطع. قد يكون الرابط قديمًا.
        </ErrorNote>
      </main>
    );
  }

  return (
    <main className="reading-column page-shell pt-8">
      <h1 className="text-2xl font-semibold leading-snug">{TITLE}</h1>

      {clip.status === "done" && clip.video_url !== null ? (
        <video
          controls
          playsInline
          preload="metadata"
          src={clip.video_url}
          className="mt-6 w-full border border-[var(--color-border)]"
        />
      ) : (
        <p className="mt-6 text-sm text-[var(--color-ink-muted)]">
          {STATUS_TEXT[clip.status]}
        </p>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-4 text-sm">
        {clip.video_url !== null ? (
          <a
            href={clip.video_url}
            download
            className="text-[var(--color-ink)] underline underline-offset-4"
          >
            تنزيل الفيديو
          </a>
        ) : null}
        <Link
          href={segmentId === null ? "/" : `/listen/${segmentId}`}
          className="text-[var(--color-ink-muted)] underline underline-offset-4"
        >
          {segmentId === null ? "إلى الأرشيف" : "إلى المقطع الكامل"}
        </Link>
      </div>

      <p className="mt-8 border-t border-[var(--color-border-subtle)] pt-4 text-xs text-[var(--color-ink-faint)]">
        {SITE_NAME} · <span dir="ltr">{siteHost()}</span>
      </p>
    </main>
  );
}
