"""A review round-trip must not erase attribution provenance.

FEAT-CAST-001 added `attribution_source` and `confidence` to Utterance so
the tool can finally distinguish "a tag said so" from "turn-tracking
guessed". `review.py` rebuilds Utterances from the imported file and set
neither, so importing a review wiped the provenance off every line in the
book — including the lines a human had just corrected by hand.

That is backwards twice over. A human decision is the HIGHEST-confidence
attribution there is, and `models.ATTRIBUTION_SOURCES` already contains a
`user` member for exactly this. It was unused.
"""

from __future__ import annotations

import pathlib

from audiobooker.models import Utterance, UtteranceType
from audiobooker.project import AudiobookProject

BOOK = """Chapter 1

"Two ounces light," said Halloran.

"The scale is wrong," said Ines.

"Then weigh it again."
"""


def _project(tmp_path: pathlib.Path) -> AudiobookProject:
    src = tmp_path / "book.txt"
    src.write_text(BOOK, encoding="utf-8")
    p = AudiobookProject.from_text(src)
    p.compile()
    return p


def _dialogue(project) -> list[Utterance]:
    return [u for c in project.chapters for u in c.utterances
            if u.utterance_type is UtteranceType.DIALOGUE]


class TestReviewImportPreservesProvenance:
    def test_compile_sets_provenance_in_the_first_place(self, tmp_path):
        """Premise check — if compile stopped setting these, the rest of
        this file would pass vacuously."""
        project = _project(tmp_path)
        d = _dialogue(project)
        assert d, "fixture produced no dialogue"
        assert any(u.attribution_source is not None for u in d), (
            "compile is not setting attribution_source — the feature this "
            "test guards is not present"
        )

    def test_a_human_edit_becomes_user_provenance(self, tmp_path):
        """The line the reviewer changed is the one we know most about."""
        project = _project(tmp_path)
        review = tmp_path / "review.txt"
        project.export_for_review(review)

        text = review.read_text(encoding="utf-8")
        assert "@Halloran" in text, text[:400]
        review.write_text(text.replace("@Halloran", "@Ines", 1), encoding="utf-8")

        project.import_reviewed(review)

        edited = [u for u in _dialogue(project) if u.speaker == "Ines"]
        assert edited, "the edit did not land"
        assert any(u.attribution_source == "user" for u in edited), (
            "a hand-corrected line must be marked 'user' — it is the "
            "highest-confidence attribution in the project, not an unknown"
        )
        assert all(u.confidence == 1.0 for u in edited
                   if u.attribution_source == "user")

    def test_untouched_lines_keep_their_original_provenance(self, tmp_path):
        """Import must not relabel the whole book as human-reviewed."""
        project = _project(tmp_path)
        # Keyed on TEXT, not id: import_reviewed regenerates every utterance
        # id, so nothing survives an id-based join. That instability is worth
        # knowing on its own — it rules out keying any future durable review
        # overlay on utterance id, which is the obvious design.
        before = {u.text: (u.attribution_source, u.confidence)
                  for u in _dialogue(project)}

        review = tmp_path / "review.txt"
        project.export_for_review(review)
        project.import_reviewed(review)

        after = _dialogue(project)
        assert after, "import produced no dialogue"
        kept = [u for u in after
                if u.text in before and before[u.text][0] is not None]
        assert kept, "no utterance survived with its text — cannot check"
        for u in kept:
            assert u.attribution_source == before[u.text][0], (
                f"{u.text[:30]!r} was relabelled "
                f"{before[u.text][0]} -> {u.attribution_source}"
            )

    def test_provenance_survives_save_and_load(self, tmp_path):
        project = _project(tmp_path)
        review = tmp_path / "review.txt"
        project.export_for_review(review)
        text = review.read_text(encoding="utf-8")
        review.write_text(text.replace("@Halloran", "@Ines", 1), encoding="utf-8")
        project.import_reviewed(review)

        proj_file = tmp_path / "b.audiobooker"
        project.save(proj_file)
        reloaded = AudiobookProject.load(proj_file)

        assert any(u.attribution_source == "user"
                   for u in _dialogue(reloaded)), (
            "provenance did not survive the project round-trip"
        )
