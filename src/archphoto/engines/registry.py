"""Registry of available engines. Empty at the scaffold stage."""

from __future__ import annotations

from archphoto.engines.base import EngineAdapter, EngineInfo


class EngineRegistry:
    """Holds discovered/registered engines. Empty until an engine is added and
    its license is verified."""

    def __init__(self) -> None:
        self._engines: dict[str, EngineAdapter] = {}

    def register(self, name: str, adapter: EngineAdapter) -> None:
        self._engines[name] = adapter

    def get(self, name: str) -> EngineAdapter:
        if name not in self._engines:
            raise KeyError(
                f"Engine {name!r} is not registered. No engine is bundled by "
                "default; register one explicitly after license verification."
            )
        return self._engines[name]

    def list(self) -> list[str]:
        return sorted(self._engines)
