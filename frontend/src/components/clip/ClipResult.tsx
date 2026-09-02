"use client";

import Link from "next/link";
import { statusLine } from "./clip-status";
import type { Clip } from "@/types/models";

interface ClipResultProps {
  clip: Clip;
  segmentId: number;
  /** Polling gave up before the render finished. */
  timedOut: boolean;
}

/**
 * What became of a render: the status line, and — once there is a file — the
 * two links that actually hand it over.
 *
 * The download link is `clip.download_url`, a same-origin address, never the
 * presigned bucket URL with `download` on it. HTML ignores that attribute
 * cross-origin, which is why every download on this site used to open the clip
 * in a new tab instead of saving it.
 */
export default function ClipResult({
  clip,
  segmentId,
  timedOut,
}: ClipResultProps) {
  const finished = clip.status === "done" || timedOut;

  return (
    <div className="mt-3 space-y-2 text-sm">
      <p role="status" className="text-[var(--color-ink-muted)]">
        {statusLine(clip.status, timedOut)}
      </p>
      {finished ? (
        <p className="flex flex-wrap items-center gap-4">
          <Link
            href={`/clip/${clip.id}?segment=${segmentId}`}
            className="text-[var(--color-ink)] underline underline-offset-4"
          >
            صفحة المقطع
          </Link>
          {clip.download_url !== null ? (
            <a
              href={clip.download_url}
              className="text-[var(--color-ink-muted)] underline underline-offset-4"
            >
              {clip.output === "audio" ? "تنزيل الصوت" : "تنزيل الفيديو"}
            </a>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}
