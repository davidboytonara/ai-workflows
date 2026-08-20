"""Utility helpers for the Google Slides skill.

Provides compatibility shims for older Python runtimes that lack certain
`importlib.metadata` attributes used by Google API libraries.
"""

from __future__ import annotations

# Patch stdlib importlib.metadata when running on older Python builds
try:  # pragma: no cover
    import importlib.metadata as _importlib_metadata  # type: ignore
except ImportError:  # pragma: no cover
    import importlib_metadata as _importlib_metadata  # type: ignore

if not hasattr(_importlib_metadata, "packages_distributions"):
    try:  # pragma: no cover
        import importlib_metadata as _importlib_metadata_backport  # type: ignore
        if hasattr(_importlib_metadata_backport, "packages_distributions"):
            _importlib_metadata.packages_distributions = _importlib_metadata_backport.packages_distributions  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover
        def _empty_packages_distributions():  # type: ignore
            return {}
        _importlib_metadata.packages_distributions = _empty_packages_distributions  # type: ignore[attr-defined]

__all__ = [
    "_importlib_metadata",
]
