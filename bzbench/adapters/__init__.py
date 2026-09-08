"""Adapter registry.

New backends (OpenAI Responses API, Anthropic API, others) register here and are
selected by `--adapter` without any change to the referee.
"""

from __future__ import annotations

from typing import Callable

from .base import AbortGame, AIPlayer, ResignGame
from .manual import ManualAdapter
from .visual import VisualAdapter

_REGISTRY: dict[str, Callable[..., AIPlayer]] = {
    "manual": ManualAdapter,
    "visual": VisualAdapter,
}


def register(name: str, factory: Callable[..., AIPlayer]) -> None:
    if name in _REGISTRY:
        raise ValueError(f"adapter {name!r} is already registered")
    _REGISTRY[name] = factory


def available() -> list[str]:
    return sorted(_REGISTRY)


def create(name: str, **kwargs) -> AIPlayer:
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"unknown adapter {name!r}; available: {', '.join(available())}"
        ) from None
    return factory(**kwargs)


__all__ = [
    "AIPlayer",
    "AbortGame",
    "ResignGame",
    "ManualAdapter",
    "VisualAdapter",
    "available",
    "create",
    "register",
]
