"""
Honorific titles — ONE source of truth for the whole pipeline (PH-B-003).

Two tables used to disagree about what a title is, and the pipeline runs both
of them over the same sentence:

* ``audiobooker.nlp.normalizer._TITLE_ABBREVIATIONS`` rewrote ``Mr.`` to
  ``Mister`` for TTS. It runs in ``AudiobookProject._preprocess_text`` and
  ``normalize_text`` defaults to True.
* ``LanguageProfile.name_titles`` listed the title prefixes that speaker
  attribution will accept in front of a name. It listed only the UNEXPANDED
  spellings, and not even all of those.

So ``"Elementary," said Mr. Holmes`` attributed to ``Mr. Holmes`` raw and to
``Mister`` after normalization — the bare ``[A-Z][a-z]+`` fallback captured the
honorific and dropped the person. ``Dr. Watson`` became ``Doctor``. And
``Prof. Lindqvist`` became ``Prof`` even BEFORE normalization, because ``Prof.``
was in the expansion table but had never been added to ``name_titles``.

Both directions now derive from :data:`TITLE_EXPANSIONS`, so a title cannot be
added to one table and forgotten in the other. :data:`TITLE_CANONICAL` maps the
spoken expansion back to the written abbreviation, which is what makes the
attributed speaker identical with and without ``normalize_text``.

This module is deliberately a leaf: it imports nothing from ``audiobooker`` so
that both the language layer and the NLP layer can depend on it. The leading
underscore keeps it out of ``_discover_profiles``' submodule scan.
"""

from __future__ import annotations


# Abbreviated title -> spoken expansion.
#
# Every entry is ALWAYS followed by a name and so is never sentence-final,
# which is why the TTS normalizer consumes the period for all of them
# (CAST-AMEND-2-009).
TITLE_EXPANSIONS: dict[str, str] = {
    "Dr.": "Doctor",
    "Mr.": "Mister",
    "Mrs.": "Missus",
    "Ms.": "Miz",
    "Prof.": "Professor",
    "Sgt.": "Sergeant",
    "Cpt.": "Captain",
    "Cpl.": "Corporal",
    "Gen.": "General",
    "Lt.": "Lieutenant",
    "Col.": "Colonel",
    "Adm.": "Admiral",
    "Rev.": "Reverend",
}

# Titles that are written out in full and never abbreviated. They take no
# period, so the TTS normalizer has nothing to do with them, but attribution
# still has to accept them in front of a name.
UNABBREVIATED_TITLES: tuple[str, ...] = (
    "Miss",
    "Captain",
    "Lord",
    "Lady",
    "Sir",
    "Madam",
    "Father",
    "Mother",
    "Sister",
    "Brother",
    "King",
    "Queen",
    "Prince",
    "Princess",
    "Old",
    "Young",
    "the",
)

# Spoken expansion (casefolded) -> the abbreviation it is written as.
#
# Attribution canonicalizes a matched title through this map, so
# ``said Mister Holmes`` (post-normalization) and ``said Mr. Holmes`` (raw)
# both yield the speaker ``Mr. Holmes`` instead of splitting one character
# into two cast members.
TITLE_CANONICAL: dict[str, str] = {
    expansion.casefold(): abbrev
    for abbrev, expansion in TITLE_EXPANSIONS.items()
}


def all_title_spellings() -> tuple[str, ...]:
    """Every accepted title spelling, longest first.

    Longest-first keeps a regex alternation from settling for a prefix (e.g.
    preferring ``Miss`` over ``Missus``); the alternation would backtrack
    anyway, but the order is load-bearing documentation of intent and costs
    nothing.
    """
    spellings = (
        set(TITLE_EXPANSIONS)
        | set(TITLE_EXPANSIONS.values())
        | set(UNABBREVIATED_TITLES)
    )
    return tuple(sorted(spellings, key=lambda s: (-len(s), s)))
