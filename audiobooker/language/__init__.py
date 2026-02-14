"""
Language profiles for Audiobooker.

Each profile bundles the language-specific rules that drive
dialogue detection, speaker attribution, and chapter parsing.
"""

from audiobooker.language.profile import LanguageProfile, get_profile

__all__ = ["LanguageProfile", "get_profile"]
