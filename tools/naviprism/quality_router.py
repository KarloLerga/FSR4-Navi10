"""Conservative reference classifier for NaviPRISM tile routing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from collections.abc import Iterable


class Route(IntEnum):
    EASY = 0
    MEDIUM = 1
    HARD = 2
    VERY_HARD = 3
    REFERENCE = 4


@dataclass(frozen=True)
class TileEvidence:
    sarm_valid: bool
    sarm_confidence: float
    disocclusion: float = 0.0
    thin_detail: bool = False
    reactive: bool = False
    specular_risk: bool = False
    history_valid: bool = True
    force_reference: bool = False


@dataclass(frozen=True)
class RouteSummary:
    routes: tuple[Route, ...]
    hard_tiles: tuple[int, ...]
    very_hard_tiles: tuple[int, ...]
    fractions: tuple[float, float, float, float, float]


def classify_tile(evidence: TileEvidence) -> Route:
    """Select a path; only high-confidence, history-safe tiles use THFA fast mode."""
    if not 0.0 <= evidence.sarm_confidence <= 1.0:
        raise ValueError("SARM confidence must be in [0, 1]")
    if not 0.0 <= evidence.disocclusion <= 1.0:
        raise ValueError("disocclusion must be in [0, 1]")
    if evidence.force_reference:
        return Route.REFERENCE
    if (not evidence.sarm_valid or evidence.sarm_confidence < 0.20
            or evidence.disocclusion > 0.75):
        return Route.VERY_HARD
    if (evidence.sarm_confidence < 0.55 or evidence.disocclusion > 0.15
            or evidence.thin_detail or evidence.reactive or evidence.specular_risk
            or not evidence.history_valid):
        return Route.HARD
    if evidence.sarm_confidence < 0.85 or evidence.disocclusion > 0.05:
        return Route.MEDIUM
    return Route.EASY


def route_tiles(evidence: Iterable[TileEvidence]) -> RouteSummary:
    routes = tuple(classify_tile(item) for item in evidence)
    counts = tuple(routes.count(route) for route in Route)
    total = len(routes)
    fractions = tuple(count / total if total else 0.0 for count in counts)
    return RouteSummary(
        routes=routes,
        hard_tiles=tuple(index for index, route in enumerate(routes)
                         if route is Route.HARD),
        very_hard_tiles=tuple(index for index, route in enumerate(routes)
                              if route is Route.VERY_HARD),
        fractions=fractions,
    )
