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

__all__ = ["STOP_WORDS", "light_stem", "normalize_for_index", "normalize_light", "stem_text"]

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


# --- Light stemming (search recall only, never display) ----------------------
#
# A conservative, Light10-style stemmer for tokens that already went through
# ``normalize_for_index``. It strips at most one clitic prefix and one suffix,
# and only when at least three letters remain, so ``الله`` stays ``الله``
# (stripping ``ال`` would leave two letters) while ``بالله`` becomes ``الله``.
#
# Single-letter prefixes other than the conjunction ``و`` are deliberately NOT
# stripped on their own: ``ب``/``ك``/``ل``/``ف`` are as often the first radical
# of the word as a clitic (``كتاب`` → ``تاب``, ``لطيف`` → ``طيف``), and a false
# stem is a false match wherever stems are compared. They are stripped only
# together with the article (``بال``, ``كال``, ``فال``, ``لل``).

_STEM_PREFIXES: tuple[str, ...] = ("وال", "بال", "فال", "كال", "لل", "ال")
"""Longest first; at most one is removed."""

_PARTICLES = "وبفكل"
"""One-letter clitics, stripped only when the definite article follows: a
bare letter is too often a radical (وحده, وقت, كتاب) to strip on its own."""

_STEM_SUFFIXES: tuple[str, ...] = ("ها", "هم", "كم", "نا", "ات", "ون", "ين")
"""At most one is removed."""

MIN_STEM_LETTERS = 3
"""A prefix or suffix is only stripped when this many letters remain."""

STOP_WORDS: frozenset[str] = frozenset(
    """
    في من علي الي عن ان ما لا هذا هذه ذلك تلك الذي التي الذين كان كانت يكون قد ثم او
    يا هو هي هم انا انت نحن انتم له لها لهم به بها بهم فيه فيها منه منها عليه عليها
    الا اذا لم لن كل بعد قبل عند مع حتي بل لكن ولكن اي ايضا هناك هنا ليس انه انها لانه
    لان لانها كما بين ذا ذي هكذا فقط
    """.split()
)
"""Function words dropped from the lexical index and from lexical queries.

Written in their ``normalize_for_index`` form (``علي`` for ``على``, ``الي`` for
``إلى``). Postgres ranking has no IDF, so without this list ``في`` and ``من``
would dominate every score.
"""


def light_stem(word: str) -> str:
    """Strip one clitic prefix and one suffix from a normalized token.

    ``الصبر`` → ``صبر``, ``بالصبر`` → ``صبر``, ``والمومنين`` → ``مومن``,
    ``الله`` → ``الله``, ``بالله`` → ``الله``. Digits and anything shorter than
    :data:`MIN_STEM_LETTERS` are returned unchanged. Idempotent.
    """
    if not word or not word[0].isalpha():
        return word
    stem = word
    for prefix in _STEM_PREFIXES:
        if stem.startswith(prefix) and len(stem) - len(prefix) >= MIN_STEM_LETTERS:
            stem = stem[len(prefix) :]
            break
    else:
        # A lone particle before the article (بالله, والله) is a clitic even
        # when the article itself must stay for the word to keep its letters.
        # Single letters are never stripped otherwise (كتاب ≠ تاب, وحده ≠ حده).
        if (
            stem[0] in _PARTICLES
            and stem[1:].startswith("ال")
            and len(stem) - 1 >= MIN_STEM_LETTERS
        ):
            stem = stem[1:]
    for suffix in _STEM_SUFFIXES:
        if stem.endswith(suffix) and len(stem) - len(suffix) >= MIN_STEM_LETTERS:
            stem = stem[: -len(suffix)]
            break
    return stem


def stem_text(normalized: str) -> str:
    """The lexical-index form of already-normalized text.

    Tokens are stemmed with :func:`light_stem`; stop words (before or after
    stemming) are dropped. Query and index text must both go through this so
    that ``الصبر`` finds ``والصبر`` and ``بالصبر``.
    """
    kept = []
    for token in normalized.split():
        if token in STOP_WORDS:
            continue
        stem = light_stem(token)
        if stem in STOP_WORDS:
            continue
        kept.append(stem)
    return " ".join(kept)
