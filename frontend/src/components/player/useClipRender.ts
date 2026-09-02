"use client";

import { useEffect, useState } from "react";
import { ApiError, createClip, getClip } from "@/lib/api";
import type { ClipPayload } from "@/lib/api";
import type { Clip } from "@/types/models";

// Same cadence as ClipComposer: ~2 minutes of polling, then hand the reader
// the clip-page link and step back.
const POLL_INTERVAL_MS = 3_000;
const MAX_POLLS = 40;

const THROTTLED = "وصلنا عدد كبير من طلباتك — جرّب مرة أخرى بعد ساعة، مع الشكر";
const GENERIC = "تعذّر إنشاء المقطع الآن. حاول مرة أخرى بعد قليل.";

/** The throttle's own answer, when it tells us how long to wait. */
function throttledFor(seconds: number): string {
  const minutes = Math.ceil(seconds / 60);
  return minutes <= 1
    ? "وصلنا عدد كبير من طلباتك — جرّب مرة أخرى بعد دقيقة، مع الشكر"
    : `وصلنا عدد كبير من طلباتك — جرّب مرة أخرى بعد ${minutes} دقيقة، مع الشكر`;
}

/**
 * One render attempt. The counter is what makes a *retry* observable: asking
 * again for a range that already has a row hands back the same clip id, so an
 * id alone would be an unchanged value and the polling effect would never
 * re-arm.
 */
interface Job {
  id: string;
  attempt: number;
}

export interface ClipRenderState {
  /** Last known clip state, null before submit. */
  clip: Clip | null;
  /** True while the create request is in flight. */
  creating: boolean;
  /**
   * A render is in flight or finished, so `submit` would do nothing. False
   * again once the job fails or polling gives up — those are the two states a
   * reader can act on, and the only two `submit` accepts a second time.
   */
  busy: boolean;
  /** Polling gave up before the render finished. */
  timedOut: boolean;
  /** Human-readable failure line, empty when fine. */
  message: string;
  submit(payload: ClipPayload): void;
}

/**
 * Create-then-poll lifecycle of one clip render — the non-visual half of
 * ClipComposer, shared with the verse page's clip modal. Unmounting stops
 * the polling; the render itself continues server-side.
 */
export function useClipRender(): ClipRenderState {
  const [job, setJob] = useState<Job | null>(null);
  const [clip, setClip] = useState<Clip | null>(null);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (job === null) return;

    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      attempts += 1;
      try {
        const next = await getClip(job.id);
        if (cancelled) return;
        setClip(next);
        if (next.status === "done" || next.status === "failed") return;
      } catch {
        if (cancelled) return;
      }
      if (attempts >= MAX_POLLS) {
        setTimedOut(true);
        return;
      }
      timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    };

    // Immediately, not after the first interval: an identical range asked for
    // twice is a cache hit that may already be `done`, and waiting three
    // seconds to discover that shows the reader "queued" for a finished clip.
    void poll();
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [job]);

  // `done` counts as busy too: there is nothing left to ask for. Only a failed
  // render, or one polling stopped watching, is worth submitting again — and
  // the API re-queues a failed row rather than handing back the wreck.
  const busy =
    creating ||
    (job !== null && !timedOut && clip !== null && clip.status !== "failed");

  const submit = (payload: ClipPayload): void => {
    if (busy) return;
    setCreating(true);
    setMessage("");
    setTimedOut(false);
    void (async () => {
      try {
        const created = await createClip(payload);
        setClip({
          id: created.id,
          status: created.status,
          output: payload.output ?? "video",
          video_url: null,
          audio_url: null,
          media_url: null,
          download_url: null,
          download_filename: null,
        });
        setJob((previous) => ({
          id: created.id,
          attempt: (previous?.attempt ?? 0) + 1,
        }));
      } catch (error) {
        setMessage(
          error instanceof ApiError && error.status === 429
            ? error.retryAfter === null
              ? THROTTLED
              : throttledFor(error.retryAfter)
            : GENERIC
        );
      } finally {
        setCreating(false);
      }
    })();
  };

  return { clip, creating, busy, timedOut, message, submit };
}
