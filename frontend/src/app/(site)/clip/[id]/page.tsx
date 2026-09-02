import type { Metadata } from "next";
import Link from "next/link";
import ErrorNote from "@/components/ErrorNote";
import { getClip } from "@/lib/api";
import { SITE_NAME, SITE_URL, siteHost } from "@/lib/site";
import type { Clip } from "@/types/models";

// The clip render finishes asynchronously, so a page rendered while the job is
// still queued would be wrong for good. The media addresses themselves are
// stable (they re-sign per request), so it is the status, not the URL, that
// keeps this page uncacheable.
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

  // `media_url` and not `video_url`: a crawler may fetch this card days after
  // the page was rendered, and a presigned bucket URL is dead in six hours.
  if (clip.media_url === null) return fallback;

  if (clip.output === "audio") {
    return {
      ...fallback,
      openGraph: {
        type: "music.song",
        siteName: SITE_NAME,
        locale: "ar_AR",
        title: TITLE,
        description: DESCRIPTION,
        url: `/clip/${id}`,
        audio: [{ url: clip.media_url, type: "audio/mp4" }],
      },
    };
  }

  return {
    ...fallback,
    openGraph: {
      type: "video.other",
      siteName: SITE_NAME,
      locale: "ar_AR",
      title: TITLE,
      description: DESCRIPTION,
      url: `/clip/${id}`,
      videos: [{ url: clip.media_url, type: "video/mp4" }],
    },
    twitter: {
      card: "player",
      title: TITLE,
      description: DESCRIPTION,
      players: [
        {
          playerUrl: `${SITE_URL}/clip/${id}`,
          streamUrl: clip.media_url,
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

      {clip.media_url === null ? (
        <p className="mt-6 text-sm text-[var(--color-ink-muted)]">
          {STATUS_TEXT[clip.status]}
        </p>
      ) : clip.output === "audio" ? (
        <audio
          controls
          preload="metadata"
          src={clip.media_url}
          className="mt-6 w-full"
        />
      ) : (
        <video
          controls
          playsInline
          preload="metadata"
          src={clip.media_url}
          className="mt-6 w-full border border-[var(--color-border)]"
        />
      )}

      <div className="mt-6 flex flex-wrap items-center gap-4 text-sm">
        {clip.download_url !== null ? (
          // Not the bucket URL with `download` on it: that attribute is ignored
          // cross-origin, so the old link played the clip instead of saving it.
          <a
            href={clip.download_url}
            className="text-[var(--color-ink)] underline underline-offset-4"
          >
            {clip.output === "audio" ? "تنزيل الصوت" : "تنزيل الفيديو"}
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
