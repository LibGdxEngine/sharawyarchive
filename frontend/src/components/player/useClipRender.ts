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

export interface ClipRenderState {
  /** Last known clip state, null before submit. */
  clip: Clip | null;
  /** True while the create request is in flight. */
  creating: boolean;
  /** True once a job was accepted (submit is one-shot). */
  submitted: boolean;
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
  const [clipId, setClipId] = useState<string | null>(null);
  const [clip, setClip] = useState<Clip | null>(null);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState("");
  const [timedOut, setTimedOut] = useState(false);

  useEffect(() => {
    if (clipId === null) return;

    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      attempts += 1;
      try {
        const next = await getClip(clipId);
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

    timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer !== undefined) clearTimeout(timer);
    };
  }, [clipId]);

  const submit = (payload: ClipPayload): void => {
    if (creating || clipId !== null) return;
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
        });
        setClipId(created.id);
      } catch (error) {
        setMessage(
          error instanceof ApiError && error.status === 429
            ? THROTTLED
            : GENERIC
        );
      } finally {
        setCreating(false);
      }
    })();
  };

  return {
    clip,
    creating,
    submitted: clipId !== null,
    timedOut,
    message,
    submit,
  };
}
