"""Domain profiles for the editor (ADR-0018, backlog I5, M019/S06).

The resolver moved to ``seams.profiles`` (ADR-0033 section 5) so ``seams check``
and the viewer read one; this module re-exports it for the viewer's callers.
"""

from seams import Profile, resolve_profile

__all__ = ["Profile", "resolve_profile"]
