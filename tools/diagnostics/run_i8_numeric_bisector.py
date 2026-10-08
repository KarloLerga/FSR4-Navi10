#!/usr/bin/env python3
"""Capture one frame of scratch after every FSR4 prefix in fresh processes.

Never reuses an FFX stateful context between cases. Never changes source math.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

STAGES = tuple(str(i) for i in range(13)) + ('full',)
SEEDS = ('zero', 'a5', 'off', '5a', 'ones')


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda: f.read(1024 * 1024), b''):
            h.update(data)
    return h.hexdigest()


def manifest_for(harness: Path) -> tuple[Path, dict]:
    for parent in (harness.parent, harness.parent.parent):
        path = parent / 'teacher/provider_i8_native_1080/manifest.json'
        if path.is_file():
            return path, json.loads(path.read_text(encoding='utf-8'))
    raise FileNotFoundError(f'missing provider shader manifest for {harness}')


def run_cases(harness: Path, sequence: Path, output: Path, *, variant: str,
              expected_scalar: bool, selected_passes: tuple[int, ...],
              stages: tuple[str, ...] = STAGES, seeds: tuple[str, ...] = ('zero',),
              repeats: int = 2, trace_frame: int = 0, timeout: int = 600) -> dict:
    harness, sequence, output = harness.resolve(), sequence.resolve(), output.resolve()
    if not harness.is_file() or not sequence.is_file():
        raise FileNotFoundError('harness and .f4seq must already exist')
    if repeats < 2 or trace_frame < 0 or not stages or not seeds:
        raise ValueError('require >=2 repeats, one or more stages/seeds and valid trace frame')
    if len(set(stages)) != len(stages) or any(s not in STAGES for s in stages):
        raise ValueError(f'invalid stages: {stages}')
    if len(set(seeds)) != len(seeds) or any(s not in SEEDS for s in seeds):
        raise ValueError(f'invalid scratch seeds: {seeds}')
    manifest_path, manifest = manifest_for(harness)
    modes = manifest.get('diagnostic_modes', {})
    if modes.get('pass11_bounds_guard') is not True:
        raise ValueError('refuse unguarded model; Pass11 race would invalidate this experiment')
    if modes.get('stable_post_math') is not False:
        raise ValueError('POST must retain literal source equations')
    if modes.get('scalar_dot4') is not expected_scalar:
        raise ValueError(f'{variant} scalar mode mismatch (manifest {modes})')
    if tuple(modes.get('scalar_dot4_pass_set', ())) != selected_passes:
        raise ValueError(f'{variant} selected-pass mismatch (manifest {modes})')
    output.mkdir(parents=True, exist_ok=True)
    result = {'schema': 'f4n10.i8-numeric-campaign.v1', 'variant': variant,
              'source_commit': manifest.get('source_commit'),
              'build_manifest': str(manifest_path.resolve()),
              'build_manifest_sha256': digest(manifest_path),
              'diagnostic_modes': modes, 'harness': str(harness),
              'harness_sha256': digest(harness), 'sequence': str(sequence),
              'sequence_file_sha256': digest(sequence),
              'stages': list(stages), 'seeds': list(seeds),
              'trace_frame': trace_frame, 'repeats': repeats, 'cases': []}
    for seed in seeds:
        for stage in stages:
            for repeat in range(1, repeats + 1):
                case_name = ('full' if stage == 'full' else f'pass_{int(stage):02d}')
                case_dir = output / f'seed_{seed}' / case_name / f'run_{repeat}'
                case_dir.mkdir(parents=True, exist_ok=True)
                report_path = case_dir / 'sequence.json'
                environment = os.environ.copy()
                for name in ('FSR4N10_LAST_MODEL_PASS', 'FSR4N10_TRACE_SCRATCH_DIR',
                             'FSR4N10_TRACE_FRAME', 'MLSR-WMMA', 'MLSR-WATERMARK'):
                    environment.pop(name, None)
                environment['FSR4N10_SCRATCH_INIT'] = seed
                environment['FSR4N10_TRACE_SCRATCH_DIR'] = str(case_dir)
                environment['FSR4N10_TRACE_FRAME'] = str(trace_frame)
                if stage != 'full':
                    environment['FSR4N10_LAST_MODEL_PASS'] = stage
                command = ([sys.executable, str(harness)] if harness.suffix.lower() == '.py'
                           else [str(harness)])
                command.extend(['--run-fsr4-provider-sequence', str(sequence), str(report_path)])
                print(f'{variant}: scratch={seed}, prefix={stage}, repeat={repeat}', flush=True)
                failure = None
                try:
                    completed = subprocess.run(command, env=environment, text=True,
                                               capture_output=True, errors='replace',
                                               timeout=timeout, check=False)
                    code = completed.returncode
                    (case_dir / 'stdout.txt').write_text(completed.stdout, encoding='utf-8')
                    (case_dir / 'stderr.txt').write_text(completed.stderr, encoding='utf-8')
                    if code:
                        failure = f'harness exited {code}'
                except subprocess.TimeoutExpired as exc:
                    code = None
                    failure = f'GPU timeout {timeout}s: {exc}'
                doc: dict = {}
                if report_path.exists():
                    try:
                        doc = json.loads(report_path.read_text(encoding='utf-8'))
                        if stage != 'full' and doc.get('diagnostic_prefix_only') is not True:
                            failure = failure or 'provider did not confirm prefix diagnostic'
                    except (OSError, ValueError) as exc:
                        failure = failure or f'invalid sequence JSON: {exc}'
                else:
                    failure = failure or 'sequence report missing'
                snapshots = {}
                label = 'full' if stage == 'full' else stage
                for context in ('instrumented', 'ordinary'):
                    name = f'frame_{trace_frame}_pass_{label}_{context}.bin'
                    path = case_dir / name
                    if path.is_file():
                        snapshots[context] = {'path': str(path), 'size': path.stat().st_size,
                                              'sha256': digest(path)}
                if set(snapshots) != {'instrumented', 'ordinary'}:
                    failure = failure or 'both scratch dumps required'
                record = {'seed': seed, 'pass_name': case_name,
                          'pass': None if stage == 'full' else int(stage),
                          'repeat': repeat, 'exit_code': code, 'error': failure,
                          'adapter': doc.get('adapter'),
                          'driver_version': doc.get('driver_version'),
                          'build_commit': doc.get('build_commit'),
                          'sequence_hash': doc.get('sequence_hash'),
                          'input_hashes': [f.get('input_frame_sha256') for f in doc.get('frames', [])],
                          'frame_hashes': [{'frame_index': f.get('frame_index'),
                                           'instrumented': f.get('instrumented_output_sha256'),
                                           'ordinary': f.get('reference_output_sha256')}
                                          for f in doc.get('frames', [])],
                          'scratch': snapshots, 'report_path': str(report_path)}
                result['cases'].append(record)
                (output / 'campaign.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--harness', type=Path, required=True)
    ap.add_argument('--sequence', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--variant', required=True)
    ap.add_argument('--arithmetic', choices=['intrinsic', 'scalar', 'hybrid'], required=True)
    ap.add_argument('--selected-passes', default='')
    ap.add_argument('--stages', nargs='+', default=list(STAGES))
    ap.add_argument('--seeds', nargs='+', default=['zero'])
    ap.add_argument('--repeats', type=int, default=2)
    ap.add_argument('--trace-frame', type=int, default=0)
    ap.add_argument('--timeout', type=int, default=600)
    args = ap.parse_args()
    try:
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parents[2] / 'tools/teacher'))
        from i8_arithmetic_pass_overlay import parse_pass_set
        selected = parse_pass_set(args.selected_passes)
        if (args.arithmetic == 'hybrid') != bool(selected):
            raise ValueError('hybrid mode requires nonempty selected passes; other modes must omit them')
        result = run_cases(args.harness, args.sequence, args.output, variant=args.variant,
                           expected_scalar=args.arithmetic == 'scalar', selected_passes=selected,
                           stages=tuple(args.stages), seeds=tuple(args.seeds),
                           repeats=args.repeats, trace_frame=args.trace_frame, timeout=args.timeout)
    except (OSError, ValueError, KeyError) as exc:
        print(f'numeric bisector campaign: {exc}', file=sys.stderr)
        return 2
    failures = [c for c in result['cases'] if c['error']]
    print(f'{len(result["cases"])} cases, failures={len(failures)}; see {args.output / "campaign.json"}')
    return 0 if not failures else 2


if __name__ == '__main__':
    raise SystemExit(main())
