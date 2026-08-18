"use client";

/**
 * /saved — List of segments saved for offline playback.
 *
 * Client component: reads from localStorage + Cache Storage at runtime.
 * No server-side data fetching (offline page must work without network).
 */

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  listOfflineSegments,
  removeSegmentOffline,
  getOfflineUsageBytes,
} from "@/lib/offline";
import type { OfflineIndexEntry } from "@/lib/offline";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "٠ ب";
  if (bytes < 1024) return `${bytes} ب`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} ك`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} م`;
}

function formatDate(ms: number): string {
  return new Date(ms).toLocaleDateString("ar-EG", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export default function SavedPage() {
  const [entries, setEntries] = useState<OfflineIndexEntry[]>([]);
  const [usageBytes, setUsageBytes] = useState(0);
  const [deleting, setDeleting] = useState<Set<number>>(new Set());

  // Load data from localStorage + Cache Storage.
  // setState is called inside a Promise callback, not synchronously in the effect body.
  const loadData = useCallback(() => {
    const current = listOfflineSegments();
    void getOfflineUsageBytes().then((bytes) => {
      setEntries(current);
      setUsageBytes(bytes);
    });
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleDelete = async (segmentId: number) => {
    setDeleting((prev) => new Set(prev).add(segmentId));
    try {
      await removeSegmentOffline(segmentId);
      loadData();
    } finally {
      setDeleting((prev) => {
        const next = new Set(prev);
        next.delete(segmentId);
        return next;
      });
    }
  };

  return (
    <main className="reading-column page-shell pt-8 pb-24">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold" style={{ color: "var(--color-ink)" }}>
          المقاطع المحفوظة
        </h1>
        {usageBytes > 0 && (
          <p className="mt-1 text-sm" style={{ color: "var(--color-ink-muted)" }}>
            الحجم الإجمالي: {formatBytes(usageBytes)}
          </p>
        )}
      </header>

      {entries.length === 0 ? (
        <div className="flex flex-col items-center gap-4 py-12 text-center">
          <p className="text-sm" style={{ color: "var(--color-ink-muted)" }}>
            لا توجد مقاطع محفوظة بعد.
          </p>
          <p className="text-sm" style={{ color: "var(--color-ink-faint)" }}>
            افتح أي مقطع واضغط «حفظ للاستماع دون اتصال» لحفظه.
          </p>
        </div>
      ) : (
        <ul className="divide-y" style={{ borderColor: "var(--color-border-subtle)" }}>
          {entries.map((entry) => (
            <li
              key={entry.segmentId}
              className="flex items-center justify-between gap-4 py-4"
            >
              <div className="min-w-0 flex-1">
                <Link
                  href={`/listen/${entry.segmentId}`}
                  className="block truncate font-medium hover:underline"
                  style={{ color: "var(--color-ink)" }}
                >
                  {entry.title}
                </Link>
                <p className="mt-0.5 text-xs" style={{ color: "var(--color-ink-muted)" }}>
                  {formatBytes(entry.bytes)} · حُفظ {formatDate(entry.savedAt)}
                </p>
              </div>

              <button
                onClick={() => void handleDelete(entry.segmentId)}
                disabled={deleting.has(entry.segmentId)}
                aria-label={`حذف ${entry.title} من المحفوظات`}
                className="flex-shrink-0 rounded px-3 py-1.5 text-xs transition-opacity disabled:opacity-40"
                style={{
                  backgroundColor: "var(--color-bg-subtle)",
                  color: "var(--color-ink-muted)",
                  border: "1px solid var(--color-border)",
                }}
              >
                {deleting.has(entry.segmentId) ? "جارٍ الحذف…" : "حذف"}
              </button>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
