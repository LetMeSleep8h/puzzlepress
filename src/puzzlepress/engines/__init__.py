"""Content engines: the derived engine kind and the registry that dispatches by it.

`kind` has no package imports, so models and validation can use it. Import the
registry (`engines.registry`) where a plan is built, not from models.
"""

from .kind import AVAILABLE, SECTIONS, EngineKind, detect_engine

__all__ = ["AVAILABLE", "SECTIONS", "EngineKind", "detect_engine"]
