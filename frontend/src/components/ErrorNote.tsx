interface ErrorNoteProps {
  children?: React.ReactNode;
}

/**
 * The quiet failure state used wherever the API is unreachable. No icon, no
 * panel, no retry theatre — one muted line in the reading column.
 */
export default function ErrorNote({ children }: ErrorNoteProps) {
  return (
    <p className="py-8 text-sm text-[var(--color-ink-muted)]">
      {children ?? "تعذّر الوصول إلى الأرشيف الآن. حاول مرة أخرى بعد قليل."}
    </p>
  );
}
