"""
Growth System - Lumen's development, learning, and personal growth.

This module enables Lumen to:
- Learn preferences from experience
- Remember relationships with visitors
- Form and track personal goals
- Build autobiographical memory
- Develop curiosity-driven exploration
- Form social bonds

All growth data persists in SQLite for continuity across sessions.
"""

from .base import GrowthSystem, get_growth_system
from .models import (
    GrowthPreference,
    VisitorRecord,
    Relationship,
    Goal,
    MemorableEvent,
    PreferenceCategory,
    GoalStatus,
    VisitorFrequency,
    VisitorType,
    BondStrength,
    normalize_visitor_identity,
)

__all__ = [
    "GrowthSystem",
    "get_growth_system",
    "GrowthPreference",
    "VisitorRecord",
    "Relationship",
    "Goal",
    "MemorableEvent",
    "PreferenceCategory",
    "GoalStatus",
    "VisitorFrequency",
    "VisitorType",
    "BondStrength",
    "normalize_visitor_identity",
]
