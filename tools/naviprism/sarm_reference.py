"""Deterministic scalar reference for NaviPRISM residual motion matching."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class SarmResult:
    valid: bool
    residual_x: float
    residual_y: float
    refined_x: float
    refined_y: float
    confidence: float
    best_cost: int
    second_cost: int
    ambiguity: float


def _pixel(surface: Sequence[Sequence[int]], x: int, y: int) -> int | None:
    if y < 0 or y >= len(surface) or x < 0 or x >= len(surface[y]):
        return None
    value = int(surface[y][x])
    if not 0 <= value <= 255:
        raise ValueError("encoded luma values must be in [0, 255]")
    return value


def _quadratic_offset(minus: int, center: int, plus: int) -> float:
    curvature = float(minus - 2 * center + plus)
    if not isfinite(curvature) or curvature <= 1.0e-6:
        return 0.0
    numerator = 0.5 * float(minus - plus)
    return max(-0.5, min(0.5, numerator / curvature))


def match_residual_motion(
    current: Sequence[Sequence[int]],
    history: Sequence[Sequence[int]],
    patch_x: int,
    patch_y: int,
    engine_x: int = 0,
    engine_y: int = 0,
    search_x: int = 3,
    search_y: int = 2,
    patch_size: int = 4,
) -> SarmResult:
    """Match encoded 4x4 luma patches around integer engine motion.

    Zero current samples are masked, matching the documented `msad4` rule.
    A candidate is valid only when every non-masked history sample is in bounds.
    Confidence combines match uniqueness and absolute match quality.
    """
    if patch_size <= 0 or search_x < 0 or search_y < 0:
        raise ValueError("patch and search dimensions must be non-negative")
    references: list[tuple[int, int, int]] = []
    for py in range(patch_size):
        for px in range(patch_size):
            sample = _pixel(current, patch_x + px, patch_y + py)
            if sample is None:
                return SarmResult(False, 0.0, 0.0, float(engine_x), float(engine_y),
                                  0.0, 0, 0, 0.0)
            if sample != 0:
                references.append((px, py, sample))
    if not references:
        return SarmResult(False, 0.0, 0.0, float(engine_x), float(engine_y),
                          0.0, 0, 0, 0.0)

    costs: dict[tuple[int, int], int] = {}
    for dy in range(-search_y, search_y + 1):
        for dx in range(-search_x, search_x + 1):
            cost = 0
            valid = True
            for px, py, reference in references:
                sample = _pixel(history,
                                patch_x + engine_x + dx + px,
                                patch_y + engine_y + dy + py)
                if sample is None or sample == 0:
                    valid = False
                    break
                cost += abs(reference - sample)
            if valid:
                costs[(dx, dy)] = cost

    if not costs:
        return SarmResult(False, 0.0, 0.0, float(engine_x), float(engine_y),
                          0.0, 0, 0, 0.0)

    ordered = sorted(costs.items(), key=lambda item: (item[1], item[0][1], item[0][0]))
    (best_dx, best_dy), best_cost = ordered[0]
    second_cost = ordered[1][1] if len(ordered) > 1 else best_cost
    ambiguity = (second_cost - best_cost) / max(float(second_cost), 1.0)
    ambiguity = max(0.0, min(1.0, ambiguity))
    quality = max(0.0, min(1.0,
                           1.0 - best_cost / (len(references) * 254.0)))
    confidence = ambiguity * quality

    dx = float(best_dx)
    dy = float(best_dy)
    left = costs.get((best_dx - 1, best_dy))
    right = costs.get((best_dx + 1, best_dy))
    if left is not None and right is not None and confidence > 0.0:
        dx += _quadratic_offset(left, best_cost, right)
    up = costs.get((best_dx, best_dy - 1))
    down = costs.get((best_dx, best_dy + 1))
    if up is not None and down is not None and confidence > 0.0:
        dy += _quadratic_offset(up, best_cost, down)

    return SarmResult(True, dx, dy, engine_x + dx, engine_y + dy,
                      confidence, best_cost, second_cost, ambiguity)
