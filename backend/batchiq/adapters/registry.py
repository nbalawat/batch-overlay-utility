"""Adapter registry: maps a vendor name to an adapter class.

New connectors register themselves with `@register("<vendor>")` (or from a
plugin package) without touching the ingestion pipeline.
"""
from __future__ import annotations

from collections.abc import Callable

from batchiq.adapters.base import NativeClient, SchedulerAdapter

_REGISTRY: dict[str, type[SchedulerAdapter]] = {}


def register(vendor: str) -> Callable[[type[SchedulerAdapter]], type[SchedulerAdapter]]:
    def deco(cls: type[SchedulerAdapter]) -> type[SchedulerAdapter]:
        cls.vendor = vendor
        _REGISTRY[vendor] = cls
        return cls
    return deco


def create(vendor: str, client: NativeClient) -> SchedulerAdapter:
    if vendor not in _REGISTRY:
        raise KeyError(f"No adapter registered for vendor '{vendor}'. Known: {sorted(_REGISTRY)}")
    return _REGISTRY[vendor](client)


def registered() -> list[str]:
    return sorted(_REGISTRY)
