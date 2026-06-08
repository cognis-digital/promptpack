"""PROMPTPACK - a versioned prompt/template registry with A/B and rollbacks.

Stdlib-only, zero-install. Stores prompt templates as immutable versions in a
JSON-backed registry, supports tagging (e.g. ``prod``), weighted A/B variants,
deterministic variant selection, rendering with ``{var}`` substitution, diffing
between versions, and rolling a tag back to any prior version.
"""
from .core import (
    Registry,
    PromptPackError,
    NotFoundError,
    ConflictError,
    DEFAULT_DB,
)

TOOL_NAME = "promptpack"
TOOL_VERSION = "1.0.0"

__all__ = [
    "Registry",
    "PromptPackError",
    "NotFoundError",
    "ConflictError",
    "DEFAULT_DB",
    "TOOL_NAME",
    "TOOL_VERSION",
]
