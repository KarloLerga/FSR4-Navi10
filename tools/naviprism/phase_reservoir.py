"""Reference model for the optional four-phase history reservoir (2x scale)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PhaseEvidence:
    color: np.ndarray
    confidence: np.ndarray
    age: np.ndarray
    depth: np.ndarray
    valid: np.ndarray


class PhaseHistoryReservoir:
    """Four LR phase slices with confidence, age and depth validity metadata.

    `source_x/source_y` passed to `reproject` are current-to-previous motion maps
    in input-resolution pixel coordinates. This reference uses nearest sampling;
    production filtering/interpolation remains a separate GPU path.
    """

    def __init__(self, height: int, width: int, channels: int = 3,
                 max_age: int = 255) -> None:
        if min(height, width, channels, max_age) <= 0:
            raise ValueError("reservoir dimensions and max_age must be positive")
        self.height = height
        self.width = width
        self.channels = channels
        self.max_age = max_age
        shape = (4, height, width)
        self.color = np.zeros((*shape, channels), dtype=np.float32)
        self.confidence = np.zeros(shape, dtype=np.float32)
        self.age = np.zeros(shape, dtype=np.uint16)
        self.depth = np.zeros(shape, dtype=np.float32)
        self.valid = np.zeros(shape, dtype=np.bool_)

    @property
    def storage_bytes(self) -> int:
        return (self.color.nbytes + self.confidence.nbytes + self.age.nbytes
                + self.depth.nbytes + self.valid.nbytes)

    @property
    def color_storage_matches_hr_history(self) -> bool:
        return self.color.nbytes == self.height * self.width * 4 * self.channels * 4

    def reset(self) -> None:
        self.color.fill(0.0)
        self.confidence.fill(0.0)
        self.age.fill(0)
        self.depth.fill(0.0)
        self.valid.fill(False)

    def reproject(self, source_x: np.ndarray, source_y: np.ndarray,
                  current_depth: np.ndarray, valid_mask: np.ndarray, *,
                  depth_threshold: float = 0.02,
                  confidence_decay: float = 0.98) -> None:
        source_x = np.asarray(source_x, dtype=np.float32)
        source_y = np.asarray(source_y, dtype=np.float32)
        current_depth = np.asarray(current_depth, dtype=np.float32)
        valid_mask = np.asarray(valid_mask, dtype=np.bool_)
        shape = (self.height, self.width)
        if any(value.shape != shape for value in
               (source_x, source_y, current_depth, valid_mask)):
            raise ValueError("reprojection maps, depth, and validity must match reservoir size")
        if depth_threshold < 0.0 or not 0.0 <= confidence_decay <= 1.0:
            raise ValueError("depth threshold and confidence decay are out of range")

        previous = PhaseEvidence(self.color.copy(), self.confidence.copy(),
                                 self.age.copy(), self.depth.copy(), self.valid.copy())
        self.color.fill(0.0)
        self.valid.fill(False)
        self.confidence.fill(0.0)
        self.age.fill(0)
        self.depth.fill(0.0)
        for y in range(self.height):
            for x in range(self.width):
                if not valid_mask[y, x]:
                    continue
                motion_x = float(source_x[y, x])
                motion_y = float(source_y[y, x])
                if not np.isfinite(motion_x) or not np.isfinite(motion_y):
                    continue
                px = int(np.floor(motion_x + 0.5))
                py = int(np.floor(motion_y + 0.5))
                if px < 0 or py < 0 or px >= self.width or py >= self.height:
                    continue
                if not np.isfinite(current_depth[y, x]):
                    continue
                for phase in range(4):
                    if not previous.valid[phase, py, px]:
                        continue
                    old_depth = float(previous.depth[phase, py, px])
                    if not np.isfinite(old_depth) or abs(old_depth - float(current_depth[y, x])) \
                            > depth_threshold:
                        continue
                    self.color[phase, y, x] = previous.color[phase, py, px]
                    self.confidence[phase, y, x] = (
                        previous.confidence[phase, py, px] * confidence_decay)
                    self.age[phase, y, x] = min(
                        int(previous.age[phase, py, px]) + 1, self.max_age)
                    self.depth[phase, y, x] = current_depth[y, x]
                    self.valid[phase, y, x] = self.confidence[phase, y, x] > 0.0

    def update(self, phase: int, color: np.ndarray, depth: np.ndarray,
               valid_mask: np.ndarray, confidence: np.ndarray | None = None) -> None:
        if not 0 <= phase < 4:
            raise ValueError("phase must be in [0, 3]")
        color = np.asarray(color, dtype=np.float32)
        depth = np.asarray(depth, dtype=np.float32)
        valid_mask = np.asarray(valid_mask, dtype=np.bool_)
        if color.shape != (self.height, self.width, self.channels):
            raise ValueError("current color shape does not match reservoir")
        if depth.shape != (self.height, self.width) or valid_mask.shape != depth.shape:
            raise ValueError("current depth and validity must match reservoir")
        if confidence is None:
            confidence_value = np.ones((self.height, self.width), dtype=np.float32)
        else:
            confidence_value = np.asarray(confidence, dtype=np.float32)
            if confidence_value.shape != depth.shape:
                raise ValueError("current confidence must match reservoir")
            if not np.isfinite(confidence_value).all() or np.any(
                    (confidence_value < 0.0) | (confidence_value > 1.0)):
                raise ValueError("confidence values must be finite and in [0, 1]")
        accepted = valid_mask & np.isfinite(depth) & np.isfinite(color).all(axis=2)
        self.valid[phase] = accepted
        self.color[phase] = np.where(accepted[..., None], color, 0.0)
        self.confidence[phase] = np.where(accepted, confidence_value, 0.0)
        self.age[phase] = 0
        self.depth[phase] = np.where(accepted, depth, 0.0)

    def evidence(self, phase: int) -> PhaseEvidence:
        if not 0 <= phase < 4:
            raise ValueError("phase must be in [0, 3]")
        return PhaseEvidence(self.color[phase].copy(), self.confidence[phase].copy(),
                             self.age[phase].copy(), self.depth[phase].copy(),
                             self.valid[phase].copy())
