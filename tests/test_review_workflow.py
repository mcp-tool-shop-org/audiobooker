"""
FT-TEST-004: Review workflow integration test.

End-to-end test covering the full review cycle:
1. Create project from string
2. Compile to utterances
3. Export review file
4. Edit review (rename speaker, add emotion)
5. Import edited review
6. Verify utterances reflect edits
"""


from audiobooker.project import AudiobookProject
from audiobooker.models import Utterance


class TestReviewWorkflowIntegration:
    """Full review workflow: compile -> export -> edit -> import -> verify."""

    def test_full_review_cycle(self, tmp_path, compiled_project):
        """Complete review workflow with speaker rename and emotion add."""
        project = compiled_project

        # Step 1: Verify project is compiled (fixture guarantees this)
        total_utterances_before = sum(len(ch.utterances) for ch in project.chapters)
        assert total_utterances_before > 0

        # Step 2: Export for review
        review_path = tmp_path / "review.txt"
        result_path = project.export_for_review(review_path)
        assert result_path.exists()
        content = result_path.read_text(encoding="utf-8")

        # Verify review file structure
        assert "# Audiobooker Review File" in content
        assert "=== " in content  # chapter markers present

        # Step 3: Edit the review file
        # Rename any "unknown" speakers to "Charlie" and add emotion "excited"
        edited = content.replace("@unknown", "@Charlie (excited)")

        # Also add emotion to narrator lines (find first @narrator and add emotion)
        edited = edited.replace("@narrator\n", "@narrator (somber)\n", 1)

        review_path.write_text(edited, encoding="utf-8")

        # Step 4: Import the edited review
        stats = project.import_reviewed(review_path)

        # Step 5: Verify stats
        assert stats["chapters_updated"] >= 1
        assert stats["utterances_imported"] > 0

        # Step 6: Verify utterances reflect edits
        all_utterances = [u for ch in project.chapters for u in ch.utterances]

        # If we renamed unknown -> Charlie, verify no "unknown" remains
        if "unknown" in content:
            speakers = {u.speaker for u in all_utterances}
            assert "unknown" not in speakers, "unknown speakers should be renamed to Charlie"
            assert "Charlie" in speakers

        # Verify narrator emotion was added on at least one utterance
        narrator_emotions = [
            u.emotion for u in all_utterances
            if u.speaker == "narrator" and u.emotion == "somber"
        ]
        assert len(narrator_emotions) >= 1, "At least one narrator should have 'somber' emotion"

    def test_review_preserves_all_chapters(self, tmp_path, compiled_project):
        """Export and reimport preserves all chapter utterances."""
        project = compiled_project
        chapter_count = len(project.chapters)

        # Export
        review_path = tmp_path / "review.txt"
        project.export_for_review(review_path)

        # Import without edits
        stats = project.import_reviewed(review_path)

        assert stats["chapters_updated"] == chapter_count
        # All chapters should still have utterances
        for ch in project.chapters:
            assert len(ch.utterances) > 0, f"Chapter {ch.index} lost utterances after roundtrip"

    def test_review_speaker_rename_updates_all_occurrences(self, tmp_path):
        """Renaming a speaker in the review file updates all their utterances."""
        project = AudiobookProject.from_string(
            '"Hello!" said Alice. "How are you?" asked Alice.',
            title="Speaker Rename Test",
        )
        project.cast("narrator", "af_heart")
        project.cast("Alice", "af_bella")
        project.compile()

        # Export
        review_path = tmp_path / "review.txt"
        project.export_for_review(review_path)

        # Rename Alice -> Alicia everywhere
        content = review_path.read_text(encoding="utf-8")
        content = content.replace("@Alice", "@Alicia")
        review_path.write_text(content, encoding="utf-8")

        # Import
        project.import_reviewed(review_path)

        # Verify all Alice utterances are now Alicia
        all_utterances = [u for ch in project.chapters for u in ch.utterances]
        alice_utterances = [u for u in all_utterances if u.speaker == "Alice"]
        alicia_utterances = [u for u in all_utterances if u.speaker == "Alicia"]

        assert len(alice_utterances) == 0, "Alice should be fully renamed"
        assert len(alicia_utterances) >= 1, "Alicia should have utterances"

    def test_review_add_emotion_to_existing_speaker(self, tmp_path):
        """Adding emotion in review file applies to imported utterances."""
        project = AudiobookProject.from_string(
            "The night was cold.\n\n\"Help!\" screamed Bob.",
            title="Emotion Add Test",
        )
        project.cast("narrator", "af_heart")
        project.cast("Bob", "bm_george")
        project.compile()

        # Export
        review_path = tmp_path / "review.txt"
        project.export_for_review(review_path)

        # Add emotion to Bob
        content = review_path.read_text(encoding="utf-8")
        content = content.replace("@Bob", "@Bob (terrified)")
        review_path.write_text(content, encoding="utf-8")

        # Import
        project.import_reviewed(review_path)

        # Verify Bob has emotion
        all_utterances = [u for ch in project.chapters for u in ch.utterances]
        bob_utterances = [u for u in all_utterances if u.speaker == "Bob"]
        for u in bob_utterances:
            assert u.emotion == "terrified", f"Bob utterance should have 'terrified' emotion, got {u.emotion}"

    def test_review_delete_utterance(self, tmp_path):
        """Deleting a speaker block from review file removes it on import."""
        project = AudiobookProject(title="Delete Test")
        project.chapters = [
            __import__("audiobooker.models", fromlist=["Chapter"]).Chapter(
                index=0,
                title="Chapter 1",
                raw_text="text",
                utterances=[
                    Utterance(speaker="narrator", text="Opening line."),
                    Utterance(speaker="Villain", text="Muahaha!", emotion="evil"),
                    Utterance(speaker="narrator", text="Closing line."),
                ],
            )
        ]

        # Export
        review_path = tmp_path / "review.txt"
        project.export_for_review(review_path)
        content = review_path.read_text(encoding="utf-8")

        # Delete the Villain block
        lines = content.split("\n")
        filtered = []
        skip = False
        for line in lines:
            if line.strip().startswith("@Villain"):
                skip = True
                continue
            if skip and (line.strip().startswith("@") or line.strip().startswith("===")):
                skip = False
            if skip and line.strip() and not line.strip().startswith("#"):
                continue
            filtered.append(line)

        review_path.write_text("\n".join(filtered), encoding="utf-8")

        # Import
        project.import_reviewed(review_path)

        # Villain should be gone
        all_utterances = [u for ch in project.chapters for u in ch.utterances]
        speakers = {u.speaker for u in all_utterances}
        assert "Villain" not in speakers, "Villain utterances should be removed"
        assert "narrator" in speakers, "Narrator should remain"

    def test_review_from_string_project(self, tmp_path):
        """Full cycle starting from from_string factory."""
        text = (
            "Chapter 1: Test\n\n"
            "The wind howled. \"Who goes there?\" demanded the guard.\n\n"
            "\"Just a traveler,\" the stranger replied softly."
        )
        project = AudiobookProject.from_string(text, title="String Test")
        project.cast("narrator", "af_heart")
        project.compile()

        # Export -> import roundtrip
        review_path = tmp_path / "review.txt"
        project.export_for_review(review_path)
        stats = project.import_reviewed(review_path)

        assert stats["chapters_updated"] >= 1
        assert stats["utterances_imported"] >= 1
