#!/usr/bin/env python3
"""GPU-ready Pass11 guard campaign, invoking existing stateful provider harness.

Uses fresh processes and records build-manifest guard flags. Does not declare
quality or production readiness. Failure of individual runs is preserved.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as inp:
        for block in iter(lambda: inp.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def load_manifest(harness: Path) -> tuple[Path, dict]:
    candidates = [parent / 'teacher' / 'provider_i8_native_1080' / 'manifest.json'
                  for parent in (harness.parent, harness.parent.parent)]
    for p in candidates:
        if p.exists():
            return p, json.loads(p.read_text(encoding='utf-8'))
    raise FileNotFoundError(f'Expected provider shader manifest next to build: {candidates}')


def run(harness: Path, sequence: Path, output: Path, seeds: list[str],
        passes: list[str], repeats: int, trace_frame: int, variant: str,
        expected_guard: bool, timeout: int = 600) -> dict:
    harness, sequence = harness.resolve(), sequence.resolve()
    if not harness.is_file() or not sequence.is_file():
        raise FileNotFoundError('Missing harness executable or sequence')
    if repeats < 2 or not all(p in ('10', '11', '12', 'full') for p in passes):
        raise ValueError('Expected >=2 repeats and pass labels 10/11/12/full')
    manifest_path, manifest = load_manifest(harness)
    actual_guard = manifest.get('diagnostic_modes', {}).get('pass11_bounds_guard')
    if actual_guard is not expected_guard:
        raise RuntimeError(f'Shader manifest guard mismatch: expected {expected_guard}, got {actual_guard}; {manifest_path}')
    output.mkdir(parents=True, exist_ok=True)
    records = []
    result = {
        'schema': 'f4n10.pass11-guard-campaign.v1', 'variant': variant,
        'expected_guard': expected_guard, 'build_manifest': str(manifest_path.resolve()),
        'manifest_sha256': sha256(manifest_path),
        'source_commit': manifest.get('source_commit'),
        'harness': str(harness), 'sequence': str(sequence),
        'trace_frame': trace_frame, 'repeats': repeats, 'cases': records,
    }
    for seed in seeds:
        if seed not in ('zero', 'a5', 'off', '5a', 'ones'):
            raise ValueError(f'Invalid scratch mode: {seed}')
        for p in passes:
            name = 'full' if p == 'full' else f'pass_{int(p):02d}'
            for repeat in range(1, repeats + 1):
                directory = output / f'seed_{seed}' / name / f'run_{repeat}'
                directory.mkdir(parents=True, exist_ok=True)
                report_path = directory / 'sequence.json'
                env = os.environ.copy()
                env.pop('MLSR-WMMA', None)
                env.pop('MLSR-WATERMARK', None)
                env['FSR4N10_SCRATCH_INIT'] = seed
                env['FSR4N10_TRACE_SCRATCH_DIR'] = str(directory.resolve())
                env['FSR4N10_TRACE_FRAME'] = str(trace_frame)
                if p == 'full':
                    env.pop('FSR4N10_LAST_MODEL_PASS', None)
                else:
                    env['FSR4N10_LAST_MODEL_PASS'] = p
                command = ([sys.executable, str(harness)] if harness.suffix.lower() == '.py'
                           else [str(harness)]) + ['--run-fsr4-provider-sequence',
                                                   str(sequence), str(report_path.resolve())]
                print(f'{variant}: seed={seed}, pass={p}, repeat={repeat}', flush=True)
                error = None
                try:
                    proc = subprocess.run(command, capture_output=True, text=True,
                                          errors='replace', timeout=timeout, env=env, check=False)
                    exit_code = proc.returncode
                    (directory / 'stdout.txt').write_text(proc.stdout, encoding='utf-8')
                    (directory / 'stderr.txt').write_text(proc.stderr, encoding='utf-8')
                    if exit_code:
                        error = f'Harness exit code {exit_code}'
                except subprocess.TimeoutExpired as exc:
                    exit_code = None
                    error = f'Timeout after {timeout}s: {exc}'
                frame_hashes = []
                seq_hash = None
                input_hashes = []
                if report_path.exists():
                    try:
                        doc = json.loads(report_path.read_text(encoding='utf-8'))
                        seq_hash = doc.get('sequence_hash')
                        input_hashes = [f['input_frame_sha256'] for f in doc['frames']]
                        frame_hashes = [{key: f.get(key) for key in (
                            'frame_index', 'input_frame_sha256',
                            'reference_output_sha256', 'instrumented_output_sha256',
                            'output_identical', 'outputs_finite')} for f in doc['frames']]
                        if p != 'full' and doc.get('diagnostic_prefix_only') is not True:
                            error = 'Provider did not acknowledge prefix truncation'
                    except (OSError, KeyError, ValueError) as exc:
                        error = f'Malformed sequence report: {exc}'
                else:
                    error = error or 'Missing sequence report'
                snapshots = {}
                for context in ('instrumented', 'ordinary'):
                    f = directory / (f'frame_{trace_frame}_pass_{"full" if p == "full" else p}_{context}.bin')
                    if f.exists():
                        snapshots[context] = {'path': str(f.resolve()), 'size': f.stat().st_size,
                                              'sha256': sha256(f)}
                if len(snapshots) != 2:
                    error = error or 'Missing scratch snapshot'
                records.append({'seed': seed, 'pass_name': name, 'pass': None if p == 'full' else int(p),
                                'repeat': repeat, 'exit_code': exit_code, 'error': error,
                                'files': snapshots, 'sequence_hash': seq_hash,
                                'input_hashes': input_hashes, 'frames': frame_hashes,
                                'report_path': str(report_path.resolve())})
                (output / 'campaign.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--harness', type=Path, required=True)
    p.add_argument('--sequence', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seeds', nargs='+', default=['zero', 'a5'])
    p.add_argument('--passes', nargs='+', default=['10', '11', '12', 'full'])
    p.add_argument('--repeats', type=int, default=3)
    p.add_argument('--trace-frame', type=int, default=0)
    p.add_argument('--timeout', type=int, default=600)
    p.add_argument('--variant', required=True)
    p.add_argument('--expected-guard', choices=['on', 'off'], required=True)
    args = p.parse_args()
    try:
        report = run(args.harness, args.sequence, args.output, args.seeds, args.passes,
                     args.repeats, args.trace_frame, args.variant,
                     args.expected_guard == 'on', args.timeout)
    except (OSError, RuntimeError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f'Pass11 campaign error: {exc}', file=sys.stderr)
        return 2
    failures = [case for case in report['cases'] if case['error']]
    print(f'Finished {len(report["cases"])} cases, failures={len(failures)}. Output: {args.output}')
    return 2 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
