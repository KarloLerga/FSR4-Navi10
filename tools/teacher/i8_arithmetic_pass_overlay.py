#!/usr/bin/env python3
"""Isolated per-pass signed-I8 arithmetic route; never edits vendor HLSL."""
from __future__ import annotations

import re
from pathlib import Path

VALID_PASSES = tuple(range(1, 13))


def parse_pass_set(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    if not re.fullmatch(r'\s*\d+(?:\s*,\s*\d+)*\s*', value):
        raise ValueError('scalar DOT4 pass set must be comma-separated integers 1..12')
    passes = tuple(int(n.strip()) for n in value.split(','))
    if any(i not in VALID_PASSES for i in passes):
        raise ValueError('scalar DOT4 pass set contains index outside 1..12')
    if len(passes) != len(set(passes)):
        raise ValueError('scalar DOT4 pass set contains duplicate indices')
    return tuple(sorted(passes))


def build_selected_wrapper(directory: Path, scalar_macro: str,
                           model_basename: str = 'passes_1080.hlsl') -> Path:
    """Create the same semantic shim as global scalar, selected only at compile call."""
    if '/' in model_basename or '\\' in model_basename or not model_basename.endswith('.hlsl'):
        raise ValueError('invalid model include filename')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'passes_1080_scalar_selected.hlsl'
    path.write_text(scalar_macro + '\n#include "' + model_basename + '"\n', encoding='utf-8')
    return path
