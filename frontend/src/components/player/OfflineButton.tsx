"use client";

/**
 * OfflineButton — Toggle button to save/remove a segment for offline playback.
 *
 * Placed near the machine-transcript marker area in Player.
 * Shows: saved state, progress while downloading, delete affordance.
 */

import { useState, useCallback } from "react";
import {
  isSegmentOffline,
  saveSegmentOffline,
  removeSegmentOffline,
} from "@/lib/offline";
import type { Segment } from "@/types/models";

interface OfflineButtonProps {
  segment: Segment;
}

type ButtonState = "idle" | "saving" | "saved" | "removing";

export default function OfflineButton({ segment }: OfflineButtonProps) {
  const segmentId = segment.id;
  // Lazy initializer: reads localStorage synchronously — no effect needed.
  // The parent (Player) must pass key={segmentId} so this component remounts
  // when the segment changes, re-running the initializer.
  const [state, setState] = useState<ButtonState>(
    () => (isSegmentOffline(segmentId) ? "saved" : "idle")
  );
  const [progress, setProgress] = useState(0);

  const handleSave = useCallback(async () => {
    setState("saving");
    setProgress(0);
    try {
      await saveSegmentOffline(segment, (fraction) =>
        setProgress(Math.round(fraction * 100))
      );
      setState("saved");
    } catch {
      setState("idle");
    }
  }, [segment]);

  const handleRemove = useCallback(async () => {
    setState("removing");
    try {
      await removeSegmentOffline(segmentId);
      setState("idle");
    } catch {
      setState("saved");
    }
  }, [segmentId]);

  const isBusy = state === "saving" || state === "removing";

  let label: string;
  let ariaLabel: string;
  if (state === "saving") {
    label = `جارٍ الحفظ ${progress}%`;
    ariaLabel = `جارٍ حفظ المقطع ${progress}%`;
  } else if (state === "saved") {
    label = "محفوظ · حذف";
    ariaLabel = "المقطع محفوظ — اضغط لحذفه";
  } else if (state === "removing") {
    label = "جارٍ الحذف…";
    ariaLabel = "جارٍ حذف المقطع";
  } else {
    label = "حفظ للاستماع دون اتصال";
    ariaLabel = "حفظ المقطع للاستماع دون اتصال";
  }

  const isSaved = state === "saved";

  return (
    <button
      onClick={isSaved ? () => void handleRemove() : () => void handleSave()}
      disabled={isBusy}
      aria-label={ariaLabel}
      aria-pressed={isSaved}
      className={`listen-chip text-xs font-medium transition-opacity${
        isSaved ? " listen-chip--active" : ""
      }`}
    >
      {/* Icon */}
      {state === "saving" ? (
        <svg
          className="h-3.5 w-3.5 animate-spin"
          xmlns="http://www.w3.org/2000/svg"
          fill="none"
          viewBox="0 0 24 24"
          aria-hidden="true"
        >
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
      ) : isSaved ? (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-3.5 w-3.5"
          viewBox="0 0 20 20"
          fill="currentColor"
          aria-hidden="true"
        >
          <path
            fillRule="evenodd"
            d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
            clipRule="evenodd"
          />
        </svg>
      ) : (
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="h-3.5 w-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
          aria-hidden="true"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"
          />
        </svg>
      )}
      {label}
    </button>
  );
}
