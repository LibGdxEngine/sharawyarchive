"use client";

import { useEffect } from "react";
import { useAudioStore } from "@/lib/audio-store";
import { addRecentSegment } from "@/lib/recent-segments";

export default function RecentSegmentsTracker() {
  useEffect(() => {
    const unsub = useAudioStore.subscribe((state, prev) => {
      const cur = state.current;
      if (cur && cur.segmentId !== prev.current?.segmentId) {
        addRecentSegment(cur.segmentId, cur.title, "recitation");
      }
    });
    return unsub;
  }, []);

  return null;
}
