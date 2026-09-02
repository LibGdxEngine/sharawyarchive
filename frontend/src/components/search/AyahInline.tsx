import Link from "next/link";
import { toArabicIndic } from "@/lib/format";
import type { SmartAyah } from "@/types/models";

/**
 * A verse quoted inside a smart answer. Props only, and only ever fed from
 * the quran app (`ayah_refs` or the verse endpoint): the model's placeholder
 * names the verse, the mushaf supplies the words. With nothing canonical to
 * show it renders nothing at all — never the placeholder, never a guess.
 */
export default function AyahInline({ ayah }: { ayah: SmartAyah | null }) {
  if (ayah === null) return null;
  const where = ayah.surah_name_ar
    ? `سورة ${ayah.surah_name_ar} · الآية ${toArabicIndic(ayah.ayah)}`
    : `${toArabicIndic(ayah.surah)}:${toArabicIndic(ayah.ayah)}`;
  return (
    <figure className="smart-ayah my-3">
      <p className="quran-text text-xl leading-[2.1]">
        {ayah.text_uthmani}{" "}
        <span className="smart-ayah-mark text-base">﴿{toArabicIndic(ayah.ayah)}﴾</span>
      </p>
      <figcaption className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--color-ink-muted)]">
        <span className="sp-badge sp-badge--gold">النص القرآني الموثّق — ليس من التفريغ الآلي</span>
        <Link href={`/surah/${ayah.surah}/ayah/${ayah.ayah}`} className="underline-offset-4 hover:underline">
          {where}
        </Link>
      </figcaption>
    </figure>
  );
}
