"""
Language profiles for Audiobooker.

Each profile bundles the language-specific rules that drive
dialogue detection, speaker attribution, and chapter parsing.
"""

from audiobooker.language.profile import (
    LanguageProfile,
    available_profiles,
    get_profile,
    register_profile,
)

__all__ = [
    "LanguageProfile",
    "available_profiles",
    "get_profile",
    "register_profile",
]
