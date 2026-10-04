"""Deterministic factorized THFA residual-filter fitting and binary packing."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from typing import Any

import numpy as np


FEATURE_COUNT = 10  # bias plus a 3x3 neighborhood residual
SPATIAL_BUCKETS = 8 * 4 * 4 * 2 * 2
TEMPORAL_BUCKETS = 3 * 4 * 2 * 2
PHASE_BUCKETS = 4
ATLAS_HEADER = struct.Struct("<8sHHHHII")
ATLAS_MAGIC = b"NAVITHFA"
ATLAS_VERSION = 1


@dataclass(frozen=True)
class ThfaAtlas:
    spatial: np.ndarray
    temporal: np.ndarray
    phase: np.ndarray
    metadata: dict[str, Any]


def _ridge_fit(features: np.ndarray, residual: np.ndarray,
               regularization: float, parent: np.ndarray) -> np.ndarray:
    if features.shape[0] == 0:
        return parent.copy()
    gram = features.T @ features
    rhs = features.T @ residual
    gram.flat[::gram.shape[0] + 1] += regularization
    rhs += regularization * parent
    return np.linalg.solve(gram, rhs)


def _fit_factor(features: np.ndarray, residual: np.ndarray, buckets: np.ndarray,
                bucket_count: int, regularization: float,
                minimum_samples: int) -> np.ndarray:
    parent = _ridge_fit(features, residual, regularization,
                        np.zeros(features.shape[1], dtype=np.float64))
    weights = np.repeat(parent[None, :], bucket_count, axis=0)
    for bucket in range(bucket_count):
        selection = buckets == bucket
        if int(np.count_nonzero(selection)) >= minimum_samples:
            weights[bucket] = _ridge_fit(features[selection], residual[selection],
                                         regularization, parent)
    return weights


def fit_thfa_atlas(features: np.ndarray, residual: np.ndarray,
                   spatial_bucket: np.ndarray, temporal_bucket: np.ndarray,
                   phase_bucket: np.ndarray, *, regularization: float = 1.0e-3,
                   minimum_samples: int = 32,
                   teacher_id: str = "unspecified",
                   source_identity: str = "unspecified",
                   input_sha256: str = "") -> ThfaAtlas:
    """Fit additive Spatial[S] + Temporal[T] + Phase[P] filter coefficients.

    Rows represent one scalar color-channel target. `features` contains a bias
    in column zero and nine same-channel neighborhood deltas from the baseline.
    Sparse buckets inherit their factor's global parent coefficients.
    """
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(residual, dtype=np.float64).reshape(-1)
    s = np.asarray(spatial_bucket, dtype=np.int64).reshape(-1)
    t = np.asarray(temporal_bucket, dtype=np.int64).reshape(-1)
    p = np.asarray(phase_bucket, dtype=np.int64).reshape(-1)
    n = x.shape[0] if x.ndim == 2 else 0
    if x.ndim != 2 or x.shape[1] != FEATURE_COUNT or n == 0:
        raise ValueError(f"features must have non-empty shape [N, {FEATURE_COUNT}]")
    if any(value.size != n for value in (y, s, t, p)):
        raise ValueError("target and descriptor arrays must have the same row count")
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("THFA training arrays must contain only finite values")
    if not np.isfinite(regularization) or regularization <= 0:
        raise ValueError("regularization must be finite and positive")
    if minimum_samples < 1:
        raise ValueError("minimum_samples must be positive")
    if np.any((s < 0) | (s >= SPATIAL_BUCKETS)):
        raise ValueError("spatial descriptor is outside the 512-bucket atlas")
    if np.any((t < 0) | (t >= TEMPORAL_BUCKETS)):
        raise ValueError("temporal descriptor is outside the 48-bucket atlas")
    if np.any((p < 0) | (p >= PHASE_BUCKETS)):
        raise ValueError("phase descriptor must be in [0, 3]")

    spatial = _fit_factor(x, y, s, SPATIAL_BUCKETS, regularization, minimum_samples)
    spatial_prediction = np.einsum("ij,ij->i", x, spatial[s])
    after_spatial = y - spatial_prediction
    temporal = _fit_factor(x, after_spatial, t, TEMPORAL_BUCKETS,
                           regularization, minimum_samples)
    temporal_prediction = np.einsum("ij,ij->i", x, temporal[t])
    after_temporal = after_spatial - temporal_prediction
    phase = _fit_factor(x, after_temporal, p, PHASE_BUCKETS,
                        regularization, minimum_samples)

    prediction = spatial_prediction + temporal_prediction
    prediction += np.einsum("ij,ij->i", x, phase[p])
    error = prediction - y
    metadata = {
        "format": "NaviPRISM THFA factorized residual atlas",
        "format_version": ATLAS_VERSION,
        "feature_count": FEATURE_COUNT,
        "spatial_buckets": SPATIAL_BUCKETS,
        "temporal_buckets": TEMPORAL_BUCKETS,
        "phase_buckets": PHASE_BUCKETS,
        "training_rows": int(n),
        "teacher_id": teacher_id,
        "source_identity": source_identity,
        "input_sha256": input_sha256,
        "regularization": float(regularization),
        "minimum_bucket_samples": int(minimum_samples),
        "spatial_bucket_counts": np.bincount(s, minlength=SPATIAL_BUCKETS).tolist(),
        "temporal_bucket_counts": np.bincount(t, minlength=TEMPORAL_BUCKETS).tolist(),
        "phase_bucket_counts": np.bincount(p, minlength=PHASE_BUCKETS).tolist(),
        "fit_rmse": float(np.sqrt(np.mean(error * error))),
    }
    return ThfaAtlas(spatial, temporal, phase, metadata)


def predict_thfa(atlas: ThfaAtlas, features: np.ndarray,
                 spatial_bucket: np.ndarray, temporal_bucket: np.ndarray,
                 phase_bucket: np.ndarray) -> np.ndarray:
    x = np.asarray(features, dtype=np.float64)
    s = np.asarray(spatial_bucket, dtype=np.int64).reshape(-1)
    t = np.asarray(temporal_bucket, dtype=np.int64).reshape(-1)
    p = np.asarray(phase_bucket, dtype=np.int64).reshape(-1)
    if x.ndim != 2 or x.shape[1] != FEATURE_COUNT:
        raise ValueError(f"features must have shape [N, {FEATURE_COUNT}]")
    if any(value.size != x.shape[0] for value in (s, t, p)):
        raise ValueError("descriptor arrays must have one entry per feature row")
    return (np.einsum("ij,ij->i", x, atlas.spatial[s])
            + np.einsum("ij,ij->i", x, atlas.temporal[t])
            + np.einsum("ij,ij->i", x, atlas.phase[p]))


def pack_thfa_atlas(atlas: ThfaAtlas) -> bytes:
    factors = (atlas.spatial, atlas.temporal, atlas.phase)
    expected_shapes = ((SPATIAL_BUCKETS, FEATURE_COUNT),
                       (TEMPORAL_BUCKETS, FEATURE_COUNT),
                       (PHASE_BUCKETS, FEATURE_COUNT))
    for value, shape in zip(factors, expected_shapes, strict=True):
        if value.shape != shape or not np.isfinite(value).all():
            raise ValueError(f"atlas factor must be finite and have shape {shape}")
    payload = b"".join(np.asarray(value, dtype="<f2").tobytes(order="C")
                       for value in factors)
    header = ATLAS_HEADER.pack(ATLAS_MAGIC, ATLAS_VERSION, FEATURE_COUNT,
                               SPATIAL_BUCKETS, TEMPORAL_BUCKETS,
                               PHASE_BUCKETS, len(payload))
    return header + payload


def write_thfa_atlas(path: Path, atlas: ThfaAtlas) -> dict[str, Any]:
    binary = pack_thfa_atlas(atlas)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(binary)
    manifest = dict(atlas.metadata)
    manifest["atlas_sha256"] = hashlib.sha256(binary).hexdigest()
    manifest_path = path.with_suffix(path.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    return manifest


def load_thfa_atlas(path: Path) -> ThfaAtlas:
    binary = path.read_bytes()
    if len(binary) < ATLAS_HEADER.size:
        raise ValueError("THFA atlas is shorter than its header")
    magic, version, feature_count, spatial_count, temporal_count, phase_count, payload_size = \
        ATLAS_HEADER.unpack_from(binary)
    if (magic != ATLAS_MAGIC or version != ATLAS_VERSION or
            feature_count != FEATURE_COUNT or spatial_count != SPATIAL_BUCKETS or
            temporal_count != TEMPORAL_BUCKETS or phase_count != PHASE_BUCKETS):
        raise ValueError("THFA atlas header is invalid or unsupported")
    payload = binary[ATLAS_HEADER.size:]
    if len(payload) != payload_size:
        raise ValueError("THFA atlas payload length does not match its header")
    manifest_path = path.with_suffix(path.suffix + ".json")
    metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    if hashlib.sha256(binary).hexdigest() != metadata.get("atlas_sha256"):
        raise ValueError("THFA atlas SHA-256 does not match its manifest")
    weights = np.frombuffer(payload, dtype="<f2").astype(np.float32)
    spatial_end = SPATIAL_BUCKETS * FEATURE_COUNT
    temporal_end = spatial_end + TEMPORAL_BUCKETS * FEATURE_COUNT
    spatial = weights[:spatial_end].reshape(SPATIAL_BUCKETS, FEATURE_COUNT)
    temporal = weights[spatial_end:temporal_end].reshape(TEMPORAL_BUCKETS, FEATURE_COUNT)
    phase = weights[temporal_end:].reshape(PHASE_BUCKETS, FEATURE_COUNT)
    if not np.isfinite(weights).all():
        raise ValueError("THFA atlas contains non-finite coefficients")
    return ThfaAtlas(spatial, temporal, phase, metadata)


def spatial_descriptor(patch: np.ndarray) -> int:
    """Hash a normalized `[0,1]` 3x3 luma patch like the runtime prepass."""
    values = np.asarray(patch, dtype=np.float64)
    if (values.shape != (3, 3) or not np.isfinite(values).all()
            or np.any((values < 0.0) | (values > 1.0))):
        raise ValueError("spatial descriptor requires a finite normalized 3x3 luma patch")
    gx = float(values[1, 2] - values[1, 0])
    gy = float(values[2, 1] - values[0, 1])
    magnitude = float(np.hypot(gx, gy))
    abs_gx = abs(gx)
    abs_gy = abs(gy)
    if abs_gx < 1.0e-8 and abs_gy < 1.0e-8:
        orientation = 0
    elif abs_gx < 1.0e-8:
        orientation = 4
    elif abs_gy < 1.0e-8:
        orientation = 0
    else:
        slope = abs_gy / abs_gx
        local_bin = 0 if slope < 0.41421356237 else 1 if slope < 1.0 \
            else 2 if slope < 2.41421356237 else 3
        same_sign = (gx > 0.0) == (gy > 0.0)
        orientation = local_bin if same_sign else local_bin + 4
    strength = 0 if magnitude < 0.08 else 1 if magnitude < 0.25 \
        else 2 if magnitude < 0.5 else 3
    coherence = min(3, int(4.0 * abs(abs(gx) - abs(gy))
                           / max(abs(gx) + abs(gy), 1.0e-8)))
    checker = abs(float(values[0, 0] + values[2, 2]
                        - values[0, 2] - values[2, 0]))
    alias_risk = int(checker > 1.0)
    contrast = int(float(values.max() - values.min()) > 0.375)
    return ((((orientation * 4 + strength) * 4 + coherence) * 2
             + alias_risk) * 2 + contrast)


def temporal_descriptor(motion_magnitude: float, confidence: float,
                        reactive: bool, history_valid: bool) -> int:
    if not np.isfinite(motion_magnitude) or not np.isfinite(confidence):
        raise ValueError("temporal descriptor inputs must be finite")
    motion = 0 if motion_magnitude < 1.0 else 1 if motion_magnitude < 4.0 else 2
    confidence_bin = min(3, max(0, int(np.clip(confidence, 0.0, 1.0) * 4.0)))
    return (((motion * 4 + confidence_bin) * 2 + int(bool(reactive))) * 2
            + int(bool(history_valid)))


def make_training_features(neighborhood: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    """Build bias-plus-nine features for grayscale or independent RGB filters."""
    values = np.asarray(neighborhood, dtype=np.float64)
    base = np.asarray(baseline, dtype=np.float64)
    if values.ndim == 3 and values.shape[1:] == (3, 3):
        base = base.reshape(-1)
        if base.size != values.shape[0]:
            raise ValueError("grayscale baseline must have one value per neighborhood")
        features = np.empty((values.shape[0], FEATURE_COUNT), dtype=np.float64)
        features[:, 0] = 1.0
        features[:, 1:] = values.reshape(values.shape[0], 9) - base[:, None]
        return features
    if values.ndim == 4 and values.shape[1:] == (3, 3, 3):
        if base.shape != (values.shape[0], 3):
            raise ValueError("RGB baseline must have shape [N,3]")
        features = np.empty((values.shape[0] * 3, FEATURE_COUNT), dtype=np.float64)
        for channel in range(3):
            rows = features[channel::3]
            rows[:, 0] = 1.0
            rows[:, 1:] = values[:, :, :, channel].reshape(values.shape[0], 9)
            rows[:, 1:] -= base[:, channel, None]
        return features
    raise ValueError("neighborhood must have shape [N,3,3] or [N,3,3,3]")


def prepare_thfa_capture(arrays: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Accept direct fit rows or raw LR neighborhood/teacher capture arrays."""
    direct_keys = {"features", "residual", "spatial_bucket", "temporal_bucket", "phase_bucket"}
    capture_keys = {"current_neighborhood", "bilinear_baseline", "teacher_target",
                    "spatial_bucket", "temporal_bucket", "phase_bucket"}
    keys = set(arrays)
    if direct_keys <= keys:
        return {key: np.asarray(arrays[key]) for key in direct_keys}
    if not capture_keys <= keys:
        missing = sorted(capture_keys - keys)
        raise ValueError("capture is missing required arrays: " + ", ".join(missing))

    neighborhoods = np.asarray(arrays["current_neighborhood"], dtype=np.float64)
    baseline = np.asarray(arrays["bilinear_baseline"], dtype=np.float64)
    teacher = np.asarray(arrays["teacher_target"], dtype=np.float64)
    if neighborhoods.ndim == 3 and neighborhoods.shape[1:] == (3, 3):
        features = make_training_features(neighborhoods, baseline)
        residual = teacher.reshape(-1) - baseline.reshape(-1)
        multiplier = 1
    elif neighborhoods.ndim == 4 and neighborhoods.shape[1:] == (3, 3, 3):
        if baseline.shape != (neighborhoods.shape[0], 3) or teacher.shape != baseline.shape:
            raise ValueError("RGB baseline and teacher target must have shape [N,3]")
        features = make_training_features(neighborhoods, baseline)
        residual = (teacher - baseline).reshape(-1)
        multiplier = 3
    else:
        raise ValueError("current_neighborhood must have shape [N,3,3] or [N,3,3,3]")

    prepared = {"features": features, "residual": residual}
    for key in ("spatial_bucket", "temporal_bucket", "phase_bucket"):
        descriptor = np.asarray(arrays[key]).reshape(-1)
        if descriptor.size != neighborhoods.shape[0]:
            raise ValueError(f"{key} must have one value per captured pixel")
        prepared[key] = np.repeat(descriptor, multiplier)
    return prepared
