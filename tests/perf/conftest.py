"""
Shared fixtures for performance benchmarks.

Generates synthetic books of configurable size for benchmarking
parse, compile, and render operations.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable

import pytest


# ---------------------------------------------------------------------------
# Synthetic book generator
# ---------------------------------------------------------------------------

_NARRATION_TEMPLATES = [
    "The wind howled through the ancient corridors of the castle.",
    "Outside, the rain battered against the windowpanes relentlessly.",
    "A long silence filled the room, broken only by the ticking of the clock.",
    "The old man sat in his chair, staring into the dying embers of the fire.",
    "Shadows danced across the walls as the candle flickered and sputtered.",
    "The road stretched endlessly before them, winding through the mountains.",
    "Far below, the river churned and foamed over jagged rocks.",
    "The forest was alive with the sounds of creatures stirring in the darkness.",
    "Morning light crept slowly across the stone floor of the monastery.",
    "The marketplace was a riot of color, noise, and the smell of spices.",
]

_DIALOGUE_TEMPLATES = [
    ('{speaker} said, "We need to leave before dawn."'),
    ('"I don\'t trust {other}," {speaker} whispered.'),
    ('"Look at this," {speaker} exclaimed, holding up the letter.'),
    ('{speaker} shouted, "Get back! It\'s not safe!"'),
    ('"Perhaps we should reconsider," {speaker} murmured thoughtfully.'),
    ('"That\'s impossible," {speaker} replied with a frown.'),
    ('"I\'ve been waiting for this moment," {speaker} said quietly.'),
    ('{speaker} laughed. "You always were the optimist."'),
    ('"Where did you find it?" {speaker} asked, eyes wide with surprise.'),
    ('"There must be another way," {speaker} pleaded.'),
]

_SPEAKERS = ["Alice", "Marcus", "Elena", "Thomas", "Sarah", "James", "Lily", "Victor"]


def generate_chapter(
    chapter_num: int,
    paragraphs: int = 40,
    dialogue_ratio: float = 0.35,
    seed: int = 42,
) -> tuple[str, str]:
    """Generate a synthetic chapter with dialogue."""
    rng = random.Random(seed + chapter_num)
    lines = []
    title = f"Chapter {chapter_num + 1}: The {rng.choice(['Journey', 'Discovery', 'Reckoning', 'Escape', 'Return', 'Arrival', 'Departure', 'Battle', 'Secret', 'Awakening'])}"

    for _ in range(paragraphs):
        if rng.random() < dialogue_ratio:
            template = rng.choice(_DIALOGUE_TEMPLATES)
            speaker = rng.choice(_SPEAKERS)
            other = rng.choice([s for s in _SPEAKERS if s != speaker])
            lines.append(template.format(speaker=speaker, other=other))
        else:
            # 2-4 narration sentences per paragraph
            para_sentences = rng.randint(2, 4)
            para = " ".join(rng.choice(_NARRATION_TEMPLATES) for _ in range(para_sentences))
            lines.append(para)

    return title, "\n\n".join(lines)


def generate_book(
    chapters: int = 10,
    paragraphs_per_chapter: int = 40,
    seed: int = 42,
) -> str:
    """Generate a full synthetic book as text."""
    parts = []
    for i in range(chapters):
        title, body = generate_chapter(i, paragraphs_per_chapter, seed=seed)
        parts.append(f"# {title}\n\n{body}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Timer utility
# ---------------------------------------------------------------------------

@dataclass
class BenchResult:
    """Result of a benchmark run."""
    name: str
    duration_s: float
    iterations: int = 1
    metadata: dict = field(default_factory=dict)

    @property
    def per_iteration_ms(self) -> float:
        return (self.duration_s / self.iterations) * 1000

    def __str__(self) -> str:
        meta = " ".join(f"{k}={v}" for k, v in self.metadata.items())
        return f"{self.name}: {self.per_iteration_ms:.1f}ms/iter ({self.iterations} iters) {meta}"


def bench(name: str, fn: Callable, iterations: int = 1, **metadata) -> BenchResult:
    """Run a benchmark and return timing result."""
    # Warm up
    if iterations > 1:
        fn()

    start = time.perf_counter()
    for _ in range(iterations):
        fn()
    elapsed = time.perf_counter() - start

    return BenchResult(
        name=name,
        duration_s=elapsed,
        iterations=iterations,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_book():
    """~10k words, 10 chapters."""
    return generate_book(chapters=10, paragraphs_per_chapter=20)


@pytest.fixture
def medium_book():
    """~50k words, 50 chapters."""
    return generate_book(chapters=50, paragraphs_per_chapter=30)


@pytest.fixture
def large_book():
    """~200k words, 100+ chapters."""
    return generate_book(chapters=120, paragraphs_per_chapter=50)
