"use client";

interface SelectionToolbarProps {
  /** Viewport coordinates the toolbar floats above (already clamped). */
  x: number;
  y: number;
  /** Whether the segment can produce a legal clip at all. */
  canClip: boolean;
  onPlay(): void;
  onClip(): void;
  onCopy(): void;
}

/**
 * The floating action pill over a word selection: play it, clip it, or copy
 * a moment link (mockup: dark pill, gold glyphs, three actions).
 */
export default function SelectionToolbar({
  x,
  y,
  canClip,
  onPlay,
  onClip,
  onCopy,
}: SelectionToolbarProps) {
  const action =
    "flex items-center gap-1.5 px-4 py-2.5 text-[13px] font-semibold text-[var(--verse-toolbar-ink)] hover:bg-white/10";

  return (
    <div
      role="toolbar"
      aria-label="إجراءات التحديد"
      className="fixed z-40 flex -translate-x-1/2 -translate-y-full overflow-hidden rounded-[10px] bg-[var(--verse-toolbar-bg)] shadow-[0_12px_34px_rgba(20,16,8,0.35)]"
      style={{ left: x, top: y }}
    >
      <button type="button" onClick={onPlay} className={action}>
        <span aria-hidden="true" className="text-[10px] text-[var(--verse-gold-soft)]">
          ▶
        </span>
        تشغيل التحديد
      </button>
      {canClip ? (
        <button
          type="button"
          onClick={onClip}
          className={`${action} border-x border-[var(--verse-toolbar-divider)]`}
        >
          <span aria-hidden="true" className="text-[var(--verse-gold-soft)]">
            ❒
          </span>
          إنشاء مقطع
        </button>
      ) : null}
      <button type="button" onClick={onCopy} className={action}>
        <span aria-hidden="true" className="text-[var(--verse-gold-soft)]">
          ⧉
        </span>
        نسخ رابط اللحظة
      </button>
    </div>
  );
}
