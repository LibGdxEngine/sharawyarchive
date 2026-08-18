"""Arabic text normalization for the Sha'rawy Archive.

This module is the single normalization utility for the project. Every Arabic
comparison — search queries, index text, ayah matching — goes through it; raw
Arabic strings are never compared directly (see ``CLAUDE.md``, rule 2).

Spec (``SHAARAWY_PROJECT_PLAN.md``, Phase 1)::

    1. NFC normalize
    2. strip tatweel U+0640
    3. strip harakat U+064B-U+0652, U+0670, U+06D6-U+06ED (Quranic annotation marks)
    4. أ إ آ ٱ ٲ ٳ → ا
    5. ة → ه           (search index only)
    6. ى → ي           (search index only)
    7. ؤ → و ,  ئ → ي  (search index only)
    8. collapse whitespace, Arabic-Indic digit variants → ASCII digits

Entry points:

``normalize_light(s)``
    Steps 1-3 only. Display fallback: keeps letter identity (آ stays آ, ة stays
    ة) while dropping vowel marks and Quranic annotation.

``normalize_for_index(s)``
    All eight steps. The form stored in ``text_normalized`` columns and the form
    every search query is passed through.

Notes on the strip range
------------------------
The harakat bucket of step 3 is implemented as the contiguous run
U+064B-U+0655, i.e. the eight harakat (fathatan … sukun) plus the combining
maddah/hamza marks U+0653/U+0654/U+0655. Because NFC runs first, a combining
mark that can compose already has: ``ا`` + U+0653 → ``آ`` (U+0622), ``ا`` +
U+0654 → ``أ``, ``ا`` + U+0655 → ``إ``, ``و`` + U+0654 → ``ؤ``, ``ي`` + U+0654
→ ``ئ``. Those precomposed letters are single codepoints, so they survive
``normalize_light`` untouched and only fold to their bare forms in
``normalize_for_index`` via steps 4 and 7 — which is the intended behaviour.
What the U+0653-U+0655 part of the range actually removes is the residue that
*cannot* compose, e.g. the maddah sitting on a superscript alef (U+0670) or a
small waw (U+06E5) in the Tanzil Uthmani text.

Order matters: NFC always first, then the character folds, and only then the
whitespace collapse.
"""

from __future__ import annotations

import unicodedata

__all__ = ["normalize_for_index", "normalize_light"]

# --- Step 2/3: codepoints removed outright -----------------------------------

TATWEEL = 0x0640
"""ARABIC TATWEEL — a pure justification glyph, never meaningful."""

HARAKAT_RANGE = range(0x064B, 0x0656)
"""Harakat U+064B-U+0652 plus combining maddah/hamza U+0653-U+0655."""

SUPERSCRIPT_ALEF = 0x0670
"""ARABIC LETTER SUPERSCRIPT ALEF (dagger alif), e.g. ٱللَّٰه → ٱلله."""

QURANIC_MARKS_RANGE = range(0x06D6, 0x06EE)
"""Quranic annotation marks U+06D6-U+06ED: waqf signs, end-of-ayah, sajdah,
small waw/yeh, small high meem, and the rest of the recitation apparatus."""

_STRIPPED_CODEPOINTS: frozenset[int] = frozenset(
    {TATWEEL, SUPERSCRIPT_ALEF} | set(HARAKAT_RANGE) | set(QURANIC_MARKS_RANGE)
)

# --- Steps 4-7: letter folds (index only) ------------------------------------

_ALEF = "ا"
_WAW = "و"
_YEH = "ي"
_HEH = "ه"

_LETTER_FOLDS: dict[str, str] = {
    # 4. hamza-carrying and wasla alef variants → bare alef
    "آ": _ALEF,  # آ ALEF WITH MADDA ABOVE
    "أ": _ALEF,  # أ ALEF WITH HAMZA ABOVE
    "إ": _ALEF,  # إ ALEF WITH HAMZA BELOW
    "ٱ": _ALEF,  # ٱ ALEF WASLA
    "ٲ": _ALEF,  # ٲ ALEF WITH WAVY HAMZA ABOVE
    "ٳ": _ALEF,  # ٳ ALEF WITH WAVY HAMZA BELOW
    # 5. ta marbuta → heh
    "ة": _HEH,  # ة
    # 6. alef maqsura → yeh
    "ى": _YEH,  # ى
    # 7. waw/yeh hamza carriers → bare carrier
    "ؤ": _WAW,  # ؤ
    "ئ": _YEH,  # ئ
}

# --- Step 8: digit folds (index only) ----------------------------------------

ARABIC_INDIC_DIGITS_START = 0x0660
"""U+0660-U+0669 ٠١٢٣٤٥٦٧٨٩."""

EXTENDED_ARABIC_INDIC_DIGITS_START = 0x06F0
"""U+06F0-U+06F9 ۰۱۲۳۴۵۶۷۸۹ (Persian/Urdu shapes)."""

_DIGIT_FOLDS: dict[str, str] = {
    chr(start + offset): chr(0x0030 + offset)
    for start in (ARABIC_INDIC_DIGITS_START, EXTENDED_ARABIC_INDIC_DIGITS_START)
    for offset in range(10)
}

# --- Translation tables, built once at import --------------------------------

_LIGHT_TABLE: dict[int, str | None] = dict.fromkeys(_STRIPPED_CODEPOINTS)

_INDEX_TABLE: dict[int, str | None] = {
    **_LIGHT_TABLE,
    **{ord(src): dst for src, dst in _LETTER_FOLDS.items()},
    **{ord(src): dst for src, dst in _DIGIT_FOLDS.items()},
}


def normalize_light(s: str) -> str:
    """Return ``s`` with vowel marks and Quranic annotation removed.

    Applies spec steps 1-3 (NFC, tatweel, harakat/dagger alif/annotation marks).
    Letter identity is preserved: ``آ`` ``أ`` ``إ`` ``ٱ`` ``ة`` ``ى`` ``ؤ`` ``ئ``
    all survive, and whitespace is left exactly as-is. Use this for display
    fallbacks, never for comparison.
    """
    return unicodedata.normalize("NFC", s).translate(_LIGHT_TABLE)


def normalize_for_index(s: str) -> str:
    """Return the canonical search/index form of ``s``.

    Applies all eight spec steps: the ``normalize_light`` strips, then the
    hamza/ta-marbuta/alef-maqsura folds, Arabic-Indic digits (both the U+0660
    and U+06F0 ranges) to ASCII, and finally whitespace runs collapsed to a
    single space with the result stripped.
    """
    folded = unicodedata.normalize("NFC", s).translate(_INDEX_TABLE)
    return " ".join(folded.split())
