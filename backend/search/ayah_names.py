"""Curated names of famous ayahs, resolved at ``normalize_for_index`` level.

Arabic readers ask for these verses by name far more often than by number, so
:func:`search.services.parse_ayah_reference` resolves the name straight to a
``(surah, ayah)`` pair. The table below is written in ordinary spelling and
folded to its index form once at import time, which means every hamza /
ta-marbuta / alef-maqsura variant a user might type — ``آية الكرسي``,
``اية الكرسى``, ``ايه الكرسي`` — lands on the same entry.

The list is deliberately short and hand-checked: a wrong entry here sends a
reader to the wrong verse of the Quran, so entries carry their source.
"""

from __future__ import annotations

from corpus.arabic import normalize_for_index

__all__ = ["AYAH_NAMES_INDEX", "FAMOUS_AYAH_NAMES", "ayah_for_name"]

FAMOUS_AYAH_NAMES: dict[str, tuple[int, int]] = {
    # The greatest ayah of the Quran per the hadith of Ubayy b. Ka'b (Muslim 810),
    # al-Baqarah 255.
    "آية الكرسي": (2, 255),
    # Ayat ad-Dayn, the debt-contract verse and the longest ayah in the mushaf,
    # al-Baqarah 282.
    "آية الدين": (2, 282),
    # Ayat an-Nur, "اللَّهُ نُورُ السَّمَاوَاتِ وَالْأَرْضِ", an-Nur 35.
    "آية النور": (24, 35),
    # Ayat as-Sayf, named so by the mufassirun (al-Tabari, Ibn Kathir) for
    # at-Tawbah 5.
    "آية السيف": (9, 5),
    # Ayat al-Mubahalah, the mutual-imprecation verse revealed over the Najran
    # delegation, Al 'Imran 61.
    "آية المباهلة": (3, 61),
}
"""Display spelling → ``(surah number, ayah number)``."""

AYAH_NAMES_INDEX: dict[str, tuple[int, int]] = {
    normalize_for_index(name): reference for name, reference in FAMOUS_AYAH_NAMES.items()
}
"""The same table keyed by :func:`corpus.arabic.normalize_for_index` output."""


def ayah_for_name(normalized_query: str) -> tuple[int, int] | None:
    """Return the ``(surah, ayah)`` a normalized famous-ayah name points at.

    ``normalized_query`` must already have been through ``normalize_for_index``.
    Returns ``None`` when the name is not in the curated table.
    """
    return AYAH_NAMES_INDEX.get(normalized_query)
