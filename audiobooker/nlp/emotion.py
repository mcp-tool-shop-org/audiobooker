"""
Emotion inference for Audiobooker.

Conservative rule+lexicon baseline (v1) that infers emotion from:
1. Attribution verbs already detected by the language profile
2. Lexicon-based sentiment from utterance text
3. Punctuation cues (! ? CAPS, ellipsis)

Only applies when confidence >= threshold; otherwise neutral.
User-set explicit emotions are never overridden.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from audiobooker.language.profile import LanguageProfile, get_profile

logger = logging.getLogger("audiobooker.nlp.emotion")

if TYPE_CHECKING:
    from audiobooker.models import Utterance


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class EmotionResult:
    """Result of emotion inference."""
    label: str          # e.g., "angry", "sad", "happy", "neutral"
    confidence: float   # 0.0 - 1.0
    source: str         # "verb", "lexicon", "punctuation", "none"


@dataclass
class EmotionRunStats:
    """
    Stats from one apply_to_utterances() pass.

    near_miss counts utterances whose best-inferred emotion fell just below
    the confidence threshold (0 < confidence < threshold) — a real candidate
    that infer() computed but conservatively left as neutral. The CLI can use
    this to hint that lowering --emotion-threshold may tag more lines.
    """
    applied: int = 0
    examined: int = 0
    near_miss: int = 0
    # Distribution of near-miss labels, e.g. {"sad": 3, "angry": 1}
    near_miss_labels: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Lexicon (small, curated, high-precision)
# ---------------------------------------------------------------------------

_EMOTION_LEXICON: dict[str, list[tuple[str, float]]] = {
    "angry": [
        (r"\b(?:furious|enraged|livid|seething|infuriated)\b", 0.9),
        (r"\b(?:angry|mad|outraged|irate|incensed)\b", 0.85),
        (r"\b(?:annoyed|irritated|frustrated)\b", 0.7),
    ],
    "sad": [
        (r"\b(?:sobbing|weeping|grieving|mourning|heartbroken)\b", 0.9),
        (r"\b(?:crying|tears|sorrowful|miserable|devastated)\b", 0.85),
        (r"\b(?:sad|unhappy|gloomy|melancholy)\b", 0.75),
    ],
    "happy": [
        (r"\b(?:ecstatic|overjoyed|elated|jubilant|thrilled)\b", 0.9),
        (r"\b(?:delighted|joyful|excited|gleeful|beaming)\b", 0.85),
        (r"\b(?:happy|pleased|cheerful|glad|smiling)\b", 0.75),
    ],
    "fearful": [
        (r"\b(?:terrified|petrified|horrified|panic)\b", 0.9),
        (r"\b(?:frightened|scared|afraid|alarmed|trembling)\b", 0.85),
        (r"\b(?:nervous|anxious|worried|uneasy)\b", 0.7),
    ],
    "whisper": [
        (r"\b(?:whispered|hissed|murmured|breathed)\b", 0.9),
        (r"\b(?:softly|quietly|hushed|under\s+(?:his|her|their)\s+breath)\b", 0.8),
    ],
    "excited": [
        (r"\b(?:can't\s+wait|incredible|amazing|fantastic|wonderful)\b", 0.8),
        (r"\b(?:eager|enthusiastic|pumped|exhilarated)\b", 0.85),
    ],
}

# Compiled patterns (lazy)
_COMPILED_LEXICON: Optional[dict[str, list[tuple[re.Pattern, float]]]] = None


def _get_lexicon() -> dict[str, list[tuple[re.Pattern, float]]]:
    """Lazily compile lexicon patterns."""
    global _COMPILED_LEXICON
    if _COMPILED_LEXICON is None:
        _COMPILED_LEXICON = {}
        for emotion, patterns in _EMOTION_LEXICON.items():
            _COMPILED_LEXICON[emotion] = [
                (re.compile(pat, re.IGNORECASE), conf)
                for pat, conf in patterns
            ]
    return _COMPILED_LEXICON


# ---------------------------------------------------------------------------
# Punctuation cues
# ---------------------------------------------------------------------------

def _punctuation_emotion(text: str) -> Optional[EmotionResult]:
    """Infer emotion from punctuation cues."""
    # Multiple exclamation marks → excited/angry
    if re.search(r"!{2,}", text):
        return EmotionResult(label="excited", confidence=0.6, source="punctuation")

    # ALL CAPS (at least 4 words)
    words = text.split()
    caps_words = sum(1 for w in words if w.isupper() and len(w) > 1)
    if caps_words >= 4:
        return EmotionResult(label="angry", confidence=0.6, source="punctuation")

    # Ellipsis → uncertain/sad (low confidence)
    if "..." in text or "\u2026" in text:
        return EmotionResult(label="sad", confidence=0.4, source="punctuation")

    return None


# ---------------------------------------------------------------------------
# Inferencer
# ---------------------------------------------------------------------------

class EmotionInferencer:
    """
    Conservative emotion inference engine.

    Applies emotion labels only when confidence >= threshold.
    Never overrides explicitly-set user emotions.

    Args:
        mode: "off" | "rule" | "auto" (default "rule").
        threshold: Minimum confidence to apply (default 0.75).
        profile: Optional LanguageProfile for verb-based hints.
    """

    def __init__(
        self,
        mode: str = "rule",
        threshold: float = 0.75,
        profile: Optional[LanguageProfile] = None,
    ) -> None:
        if mode not in ("off", "rule", "auto"):
            raise ValueError(f"Invalid emotion_mode: {mode!r}. Must be off|rule|auto.")
        self.mode = mode
        self.threshold = threshold
        self.profile = profile or get_profile("en")
        # Stats from the most recent apply_to_utterances() pass. project.py /
        # the CLI can read this after a run to surface near-miss hints without
        # changing the int return contract of apply_to_utterances().
        self.last_run_stats: EmotionRunStats = EmotionRunStats()

        # F-CORE-B-011: Log when lexicon won't match non-English text
        lang = getattr(self.profile, "code", "en")
        if lang != "en":
            logger.info(
                "Emotion lexicon is English-only. Language '%s' will rely on "
                "punctuation cues and verb hints; lexicon matches may be less accurate.",
                lang,
            )

    def infer(
        self,
        utterance_text: str,
        context: str = "",
        existing_emotion: Optional[str] = None,
    ) -> EmotionResult:
        """
        Infer emotion for an utterance.

        Args:
            utterance_text: The text of the utterance.
            context: Surrounding text (paragraph, attribution phrase).
            existing_emotion: Already-set emotion (from verb or user override).

        Returns:
            EmotionResult with label, confidence, source.
        """
        if self.mode == "off":
            return EmotionResult(label="neutral", confidence=0.0, source="none")

        # If user already set an emotion, preserve it with max confidence
        if existing_emotion:
            return EmotionResult(
                label=existing_emotion, confidence=1.0, source="explicit"
            )

        combined = f"{context} {utterance_text}".strip()

        # 1. Check verb-based hints from language profile (highest priority)
        verb_result = self._check_verb_hints(combined)
        if verb_result and verb_result.confidence >= self.threshold:
            return verb_result

        # 2. Check lexicon
        lex_result = self._check_lexicon(combined)
        if lex_result and lex_result.confidence >= self.threshold:
            return lex_result

        # 3. Check punctuation
        punct_result = _punctuation_emotion(utterance_text)
        if punct_result and punct_result.confidence >= self.threshold:
            return punct_result

        # Below threshold — return neutral
        best = verb_result or lex_result or punct_result
        if best and best.confidence > 0:
            # Return the best candidate even if below threshold,
            # so callers can see what was almost inferred
            return EmotionResult(
                label="neutral", confidence=best.confidence, source=best.source
            )

        return EmotionResult(label="neutral", confidence=0.0, source="none")

    def _check_verb_hints(self, text: str) -> Optional[EmotionResult]:
        """Check if text contains emotion-hinting verbs from the profile."""
        pattern = self.profile.build_emotion_verb_pattern()
        if pattern is None:
            return None

        match = pattern.search(text)
        if match:
            verb = match.group(1).lower()
            emotion = self.profile.emotion_hints.get(verb)
            if emotion:
                return EmotionResult(
                    label=emotion, confidence=0.85, source="verb"
                )
        return None

    def _check_lexicon(self, text: str) -> Optional[EmotionResult]:
        """Check text against emotion lexicon."""
        lexicon = _get_lexicon()
        best: Optional[EmotionResult] = None

        for emotion, patterns in lexicon.items():
            for pat, base_conf in patterns:
                if pat.search(text):
                    if best is None or base_conf > best.confidence:
                        best = EmotionResult(
                            label=emotion, confidence=base_conf, source="lexicon"
                        )

        return best

    def apply_to_utterances(
        self,
        utterances: list["Utterance"],
        chapter_text: str = "",
    ) -> int:
        """
        Apply emotion inference to a list of utterances in-place.

        Only updates utterances that don't already have an emotion set.

        Args:
            utterances: List of utterances to process.
            chapter_text: Full chapter text for context.

        Returns:
            Number of emotions applied (int). For richer stats — including the
            count of near-miss utterances that fell just below the threshold —
            read ``self.last_run_stats`` after the call. The bare-int return is
            preserved for backward compatibility.
        """
        stats = EmotionRunStats()
        context_window = 200  # chars around the utterance position

        for utt in utterances:
            if utt.emotion:
                continue  # Already has emotion — don't override

            stats.examined += 1

            # Scope context to a narrow window around the utterance
            # to avoid false-positive emotion tagging from distant text.
            context = ""
            if chapter_text and utt.text:
                pos = chapter_text.find(utt.text)
                if pos >= 0:
                    start = max(0, pos - context_window)
                    end = min(len(chapter_text), pos + len(utt.text) + context_window)
                    context = chapter_text[start:end]

            result = self.infer(utt.text, context=context)
            if result.label != "neutral" and result.confidence >= self.threshold:
                utt.emotion = result.label
                stats.applied += 1
            elif 0.0 < result.confidence < self.threshold and result.source != "none":
                # Near miss: infer() computed a real candidate but
                # conservatively returned neutral because it was below
                # threshold. infer() reports the candidate's source/confidence
                # while relabelling to "neutral", so recover the candidate
                # label from the original source.
                near_label = self._near_miss_label(utt.text, context)
                stats.near_miss += 1
                if near_label:
                    stats.near_miss_labels[near_label] = (
                        stats.near_miss_labels.get(near_label, 0) + 1
                    )

        self.last_run_stats = stats
        return stats.applied

    def _near_miss_label(self, utterance_text: str, context: str) -> Optional[str]:
        """
        Recover the candidate emotion label for a near-miss utterance.

        infer() relabels below-threshold candidates to "neutral" but keeps the
        source/confidence, so the original label is recomputed here for the
        near-miss distribution. Returns None if no candidate label is found.
        """
        combined = f"{context} {utterance_text}".strip()
        verb_result = self._check_verb_hints(combined)
        if verb_result and verb_result.confidence > 0:
            return verb_result.label
        lex_result = self._check_lexicon(combined)
        if lex_result and lex_result.confidence > 0:
            return lex_result.label
        punct_result = _punctuation_emotion(utterance_text)
        if punct_result and punct_result.confidence > 0:
            return punct_result.label
        return None
