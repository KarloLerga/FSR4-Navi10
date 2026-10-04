"""Scalar byte-order and accumulation reference for HLSL msad4."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


MAX_MASKED_BYTE = 255
MAX_UNMASKED_DIFFERENCE = 254
MAX_DIFFERENCE_PER_MSAD4_LANE = 4 * MAX_UNMASKED_DIFFERENCE
SAFE_CALLS_PER_CHUNK = 48
MAX_ACCUMULATOR = 65_535


def _byte(value: int, index: int) -> int:
    return (value >> (8 * index)) & 0xFF


def source_byte(source_low: int, source_high: int, index: int) -> int:
    """Read the 8-byte source as little-endian bytes, matching HLSL uint2."""
    if not 0 <= index < 8:
        raise ValueError("source byte index must be in [0, 7]")
    word = source_low if index < 4 else source_high
    return _byte(word, index if index < 4 else index - 4)


def msad4_reference(
    reference: int,
    source_low: int,
    source_high: int,
    accum: Sequence[int] = (0, 0, 0, 0),
) -> tuple[int, int, int, int]:
    """Return four shifted SAD lanes; zero reference bytes mask contributions."""
    if len(accum) != 4:
        raise ValueError("msad4 accumulator must contain four lanes")
    result = list(accum)
    for alignment in range(4):
        for ref_index in range(4):
            ref = _byte(reference, ref_index)
            if ref == 0:
                continue
            sample = source_byte(source_low, source_high, alignment + ref_index)
            result[alignment] += abs(ref - sample)
    return tuple(result)


def encode_valid_bytes(values: Iterable[int]) -> tuple[int, ...]:
    """Encode logical 0..254 as stored 1..255, reserving zero for mask padding."""
    encoded = []
    for value in values:
        if not 0 <= value <= 254:
            raise ValueError("logical image bytes must be in [0, 254]")
        encoded.append(value + 1)
    return tuple(encoded)


def pack_bytes(values: Sequence[int]) -> int:
    if len(values) != 4 or any(not 0 <= value <= 255 for value in values):
        raise ValueError("exactly four byte values are required")
    return sum(value << (8 * index) for index, value in enumerate(values))


def chunked_msad4_sum(samples: Sequence[tuple[int, int, int]],
                     chunk_size: int = SAFE_CALLS_PER_CHUNK
                     ) -> tuple[int, int, int, int]:
    """Accumulate with a fresh 32-bit SIMD accumulator every bounded chunk."""
    if not 1 <= chunk_size <= SAFE_CALLS_PER_CHUNK:
        raise ValueError(f"chunk_size must be in [1, {SAFE_CALLS_PER_CHUNK}]")
    total = [0, 0, 0, 0]
    for start in range(0, len(samples), chunk_size):
        partial = [0, 0, 0, 0]
        for reference, source_low, source_high in samples[start:start + chunk_size]:
            partial = list(msad4_reference(reference, source_low, source_high, partial))
        if any(value > MAX_ACCUMULATOR for value in partial):
            raise OverflowError("one msad4 accumulation chunk exceeds 65535")
        for lane in range(4):
            total[lane] += partial[lane]
    return tuple(total)
