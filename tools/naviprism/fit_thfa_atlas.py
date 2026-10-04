from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import numpy as np

from thfa_atlas import fit_thfa_atlas, prepare_thfa_capture, write_thfa_atlas


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit a factorized NaviPRISM THFA filter atlas from captured targets."
    )
    parser.add_argument("dataset", type=Path,
                        help="NPZ with raw capture arrays or precomputed fit rows and descriptors")
    parser.add_argument("output", type=Path, help="Output .thfa atlas path")
    parser.add_argument("--teacher-id", required=True,
                        help="Stable identifier for the captured reconstruction teacher")
    parser.add_argument("--source-identity", required=True,
                        help="Capture provenance, model hash, and sequence identity")
    parser.add_argument("--regularization", type=float, default=1.0e-3)
    parser.add_argument("--minimum-bucket-samples", type=int, default=32)
    args = parser.parse_args()

    dataset_bytes = args.dataset.read_bytes()
    digest = hashlib.sha256(dataset_bytes).hexdigest()
    with np.load(args.dataset, allow_pickle=False) as archive:
        arrays = prepare_thfa_capture({key: archive[key] for key in archive.files})

    atlas = fit_thfa_atlas(
        arrays["features"], arrays["residual"], arrays["spatial_bucket"],
        arrays["temporal_bucket"], arrays["phase_bucket"],
        regularization=args.regularization,
        minimum_samples=args.minimum_bucket_samples,
        teacher_id=args.teacher_id,
        source_identity=args.source_identity,
        input_sha256=digest,
    )
    manifest = write_thfa_atlas(args.output, atlas)
    print(f"Wrote {args.output} ({args.output.stat().st_size} bytes)")
    print(f"Teacher: {manifest['teacher_id']}; source: {manifest['source_identity']}")
    print(f"Rows: {manifest['training_rows']}; fit RMSE: {manifest['fit_rmse']:.8f}")
    print(f"Input SHA-256: {digest}; atlas SHA-256: {manifest['atlas_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
