#!/usr/bin/env python3
"""Parse exact output tensor layouts from the pinned FSR4 I8/1080 HLSL.

This intentionally fails for unknown layouts. The first per-pass difference
must be measured in *valid output bytes*, not arbitrary reused scratch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

MODEL = Path('third_party/fidelityfx-fsr4-source/Kits/FidelityFX/upscalers/fsr4/internal/shaders/fsr4_model_v07_i8_native/passes_1080.hlsl')
SCRATCH_BYTES = 20_880_256


@dataclass(frozen=True)
class Tensor:
    pass_index: int
    name: str
    dtype: str
    width: int
    height: int
    channels: int
    stride_x: int
    stride_y: int
    stride_channel: int
    byte_base: int
    byte_count: int
    quantization_scale: float | None = None


def single(regex: str, content: str, name: str) -> re.Match[str]:
    hits = list(re.finditer(regex, content, flags=re.MULTILINE))
    if len(hits) != 1:
        raise ValueError(f'{name}: expected exactly one match, got {len(hits)}')
    return hits[0]


def parse_contracts(source: str) -> list[Tensor]:
    source = source.replace('\r\n', '\n')
    results: list[Tensor] = []
    for index in range(1, 13):
        start = single(rf'^\s*#ifdef MLSR_PASS_{index}\s*$', source, f'pass {index} start')
        end_token = f'#endif // #ifdef MLSR_PASS_{index}'
        end_offset = source.find(end_token, start.end())
        if end_offset < 0:
            raise ValueError(f'pass {index}: missing end delimiter')
        section = source[start.end():end_offset]
        slice_name = f'slice_{index * 2}'
        # Assert the target is the actual final argument of precisely one pass entry.
        single(rf',\s*{slice_name},\s*computeShaderParams\s*\);', section,
               f'pass {index} final output call')
        def vec(key: str) -> tuple[int, int, int]:
            match = single(
                rf'const uint3 {key}_{slice_name}\s*=\s*uint3\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\);',
                section, f'pass {index} {key}')
            return tuple(map(int, match.groups()))

        width, height, channels = vec('logicalSize')
        storage_size = vec('storageSize')
        stride_x, stride_y, stride_channel = vec('tensorByteStrides')
        start_group = single(
            rf'const int threadGroupByteOffsetInTensor_{slice_name}\s*=\s*dot\(', section,
            f'pass {index} group offset')
        _ = start_group
        declaration = single(
            rf'const (QuantizedTensor3i8_NHWC|Tensor3i8_NHWC)<RWBufferStorage>\s+{slice_name}\s*=\s*\{{[^;]*?threadGroupByteOffsetInTensor_{slice_name}\s*\+\s*(\d+)\s*,',
            section, f'pass {index} concrete scratch descriptor')
        dtype, offset = declaration.group(1), int(declaration.group(2))
        scale_match = re.search(
            rf'const float quantizationScale_{slice_name}\s*=\s*([+\-\deE.]+)\s*;', section)
        scale = float(scale_match.group(1)) if scale_match else None
        if dtype == 'QuantizedTensor3i8_NHWC' and (scale is None or scale <= 0):
            raise ValueError(f'pass {index}: quantized output missing valid scale')
        if dtype == 'Tensor3i8_NHWC' and scale is not None:
            raise ValueError(f'pass {index}: unexpected quantization scale')
        count = width * height * channels
        if (width <= 0 or height <= 0 or channels <= 0 or
            storage_size != (width, height, channels) or
            stride_channel != 1 or stride_x != channels or
            stride_y != width * channels or offset < 0 or
            offset + count > SCRATCH_BYTES):
            raise ValueError(f'pass {index}: not a safe contiguous NHWC byte tensor')
        results.append(Tensor(index, slice_name, dtype, width, height, channels,
                              stride_x, stride_y, stride_channel, offset, count, scale))
    p11 = results[10]
    if (p11.width, p11.height, p11.channels, p11.byte_base) != (960, 540, 16, 12_441_600):
        raise ValueError('pinned Native1080 Pass 11 contract changed')
    if [x.name for x in results] != [f'slice_{i*2}' for i in range(1, 13)]:
        raise ValueError('missing, duplicate or reordered output slices')
    return results


def parse_file(path: Path) -> dict:
    contents = path.read_bytes()
    tensors = parse_contracts(contents.decode('utf-8-sig'))
    return {'schema': 'f4n10.i8-1080-output-contracts.v1',
            'source_file': str(path.resolve()),
            'source_sha256': hashlib.sha256(contents).hexdigest(),
            'scratch_bytes': SCRATCH_BYTES,
            'passes': [asdict(t) for t in tensors]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    output = parse_file(args.repo / MODEL)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    print(f'Parsed {len(output["passes"])} pinned I8 tensor output layouts into {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
