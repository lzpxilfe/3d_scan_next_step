"""Adapters to existing photogrammetry engines (baseline path).

The engine choice is UNDECIDED [O] (e.g. COLMAP, OpenDroneMap, or others). This
package defines a thin interface so the baseline path can call an external
engine while the research path (recon/) stays separate. No engine is bundled or
claimed to be verified here; each engine's license and version must be checked
(see NOTICE) before redistribution.
"""

from archphoto.engines.base import EngineAdapter, EngineCapability
from archphoto.engines.registry import EngineRegistry

__all__ = ["EngineAdapter", "EngineCapability", "EngineRegistry"]
