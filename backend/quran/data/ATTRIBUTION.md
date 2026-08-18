# Quran text attribution

The files in this directory are **not** produced by this project. They are
verbatim copies of the Tanzil Quran text, cached here so that `manage.py
import_quran` is reproducible and offline-safe. Nothing in the pipeline —
least of all ASR output — may ever overwrite them (see `CLAUDE.md`, rule 1).

## Files

Common query string for both text files:
`outType=txt-2&marks=true&sajdah=true&tatweel=true&agree=true` — the state the
download form at <https://tanzil.net/download/> is in by default.

| File | Source URL |
| --- | --- |
| `quran-uthmani.txt` | `https://tanzil.net/pub/download/index.php?quranType=uthmani&<options>` |
| `quran-simple.txt` | `https://tanzil.net/pub/download/index.php?quranType=simple&<options>` |
| `quran-data.xml` | `https://tanzil.net/res/text/metadata/quran-data.xml` |

`outType=txt-2` is the "Text (with aya numbers)" variant: each data line is
`surah|ayah|text`, wrapped by a `#`-prefixed licence header and footer. Both
text files carry exactly 6236 data lines; `quran-data.xml` carries 114 `<sura>`
elements plus the juz / hizb-quarter / page / sajda start markers.

To refresh, re-run the three URLs above and re-check those counts before
committing. `import_quran` will also fetch any missing file on first run.

## The sura-opening basmala

Tanzil's **XML** export keeps the opening basmala in a separate attribute
(`<aya index="1" text="الٓمٓ" bismillah="بِسْمِ ٱللَّهِ …"/>`), but the **txt**
exports inline it into the text of ayah 1. So the raw `2|1|` line here reads
`بِسْمِ ٱللَّهِ ٱلرَّحْمَـٰنِ ٱلرَّحِيمِ الٓمٓ`, while ayah 2:1 is really just
`الٓمٓ`.

The files are kept exactly as downloaded; `quran.tanzil.strip_sura_bismillah`
detaches the prefix at parse time, using the text of ayah 1:1 (which *is* the
basmala) as the literal prefix to remove. Sura 1 and At-Tawbah (9) are exempt,
so the import asserts that exactly 112 ayahs were shortened.

## Licence

Quran text copyright © Tanzil.net — <https://tanzil.net>.

The Uthmani and simple texts are distributed by Tanzil under the terms
reproduced in the header of each `.txt` file; `quran-data.xml` is released under
CC-BY (`license="cc-by"` in the document root). Their terms, in short:

- The text must not be modified in any way; it is used here verbatim.
- The copyright notice must be included in all verbatim copies and reproduced
  appropriately in any file containing a substantial portion of the text —
  which is what this document does.
- The text may not be used for commercial purposes without permission from
  Tanzil.

Updates and the full licence text: <https://tanzil.net/updates/>.

Please do not strip the `#` comment blocks from the `.txt` files; they carry the
upstream notice. The parser in `quran/tanzil.py` ignores them.
