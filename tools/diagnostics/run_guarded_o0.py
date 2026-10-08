#!/usr/bin/env python3
"""Run the EXISTING source-correctness O0 tests on a guarded full provider.

All failures are recorded, not concealed; no thresholds or teacher gates patched.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def add_step(steps: list[dict], name: str, command: list[str],
             cwd: Path, logs: Path, *, required: bool = True) -> bool:
    logs.mkdir(parents=True, exist_ok=True)
    print(f'[O0] {name}', flush=True)
    output = logs / (name + '.stdout.txt')
    errors = logs / (name + '.stderr.txt')
    try:
        env = os.environ.copy()
        for key in ('FSR4N10_LAST_MODEL_PASS', 'FSR4N10_TRACE_SCRATCH_DIR',
                    'FSR4N10_SCRATCH_INIT', 'FSR4N10_TRACE_FRAME',
                    'MLSR-WMMA', 'MLSR-WATERMARK'):
            env.pop(key, None)
        proc = subprocess.run(command, cwd=cwd, env=env, text=True,
                              capture_output=True, errors='replace',
                              timeout=1200, check=False)
        output.write_text(proc.stdout, encoding='utf-8')
        errors.write_text(proc.stderr, encoding='utf-8')
        entry = {'name': name, 'command': command, 'exit_code': proc.returncode,
                 'passed': proc.returncode == 0, 'required': required,
                 'stdout': str(output), 'stderr': str(errors)}
    except (OSError, subprocess.TimeoutExpired) as exc:
        entry = {'name': name, 'command': command, 'exit_code': None,
                 'passed': False, 'required': required, 'error': str(exc)}
    steps.append(entry)
    return bool(entry['passed'])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--repo', type=Path, required=True)
    ap.add_argument('--harness', type=Path, required=True)
    ap.add_argument('--sequence', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--arithmetic', choices=['scalar', 'intrinsic'], required=True)
    ap.add_argument('--fsr3-report', type=Path)
    ap.add_argument('--basis-audit', type=Path)
    args = ap.parse_args()
    repo, harness, sequence, output = (x.resolve() for x in
                                       (args.repo, args.harness, args.sequence, args.output))
    if not harness.is_file() or not sequence.is_file():
        ap.error('missing Windows harness or .f4seq')
    sys.path.insert(0, str(repo / 'tools/diagnostics'))
    from run_i8_numeric_bisector import manifest_for
    manifest_path, manifest = manifest_for(harness)
    modes = manifest.get('diagnostic_modes', {})
    if (modes.get('pass11_bounds_guard') is not True or
        modes.get('scalar_dot4') is not (args.arithmetic == 'scalar') or
        modes.get('stable_post_math') is not False or
        modes.get('scalar_dot4_pass_set', []) not in ([], None)):
        ap.error(f'invalid O0 baseline; require guarded {args.arithmetic} literal path, no hybrid')
    output.mkdir(parents=True, exist_ok=True)
    logs = output / 'logs'
    py = sys.executable
    steps: list[dict] = []
    report_a, report_b = (output / f'full_{n}.json' for n in ('a', 'b'))
    cap_a, cap_b = (output / f'captures_{n}' for n in ('a', 'b'))
    for label, report, captures in (('a', report_a, cap_a), ('b', report_b, cap_b)):
        add_step(steps, 'sequence_' + label,
                 [py, str(repo / 'tools/sequence/run_fsr4_teacher.py'),
                  str(harness), str(sequence), str(report),
                  '--capture-root', str(captures)], repo, logs)
    if report_a.is_file() and report_b.is_file():
        add_step(steps, 'sequence_repeatability',
                 [py, str(repo / 'tools/oracles/compare_fsr4_sequence_repeatability.py'),
                  str(report_a), str(report_b),
                  '--first-capture-root', str(cap_a),
                  '--repeat-capture-root', str(cap_b),
                  '--output', str(output / 'repeatability.json')], repo, logs)
    captures = sorted(cap_a.glob('frame_*.f4cap'))
    if captures:
        add_step(steps, 'cpu_literal_post',
                 [py, str(repo / 'tools/oracles/replay_fsr4_post.py'),
                  *map(str, captures), '--output', str(output / 'cpu_post.json')], repo, logs)
        add_step(steps, 'reference_parity',
                 [py, str(repo / 'tools/oracles/compare_fsr4_capture_reference.py'),
                  *map(str, captures), '--output', str(output / 'instrumentation.json')], repo, logs)
        for capture in captures:
            frame = capture.stem.removeprefix('frame_')
            post_case = output / f'frame_{frame}.f4postcase'
            if add_step(steps, f'postcase_frame_{frame}',
                [py, str(repo / 'tools/oracles/export_fsr4_post_case.py'),
                 str(capture), str(post_case)], repo, logs):
                add_step(steps, f'gpu_post_frame_{frame}',
                         [str(harness), '--run-fsr4-post-gpu-oracle', str(post_case),
                          str(output / f'gpu_post_frame_{frame}.json')], repo, logs)
    else:
        steps.append({'name': 'capture_presence', 'passed': False, 'required': True,
                      'error': 'no valid audit .f4cap archives were generated'})
    add_step(steps, 'dot4_conformance',
             [str(harness), '--run-dot4-conformance', str(output / 'dot4.json')], repo, logs)

    fsr3 = args.fsr3_report.resolve() if args.fsr3_report else repo / 'artifacts/results/fsr3_rootcause_basis_sequence.json'
    basis = args.basis_audit.resolve() if args.basis_audit else repo / 'artifacts/results/fsr3_delta_basis_capture_audit.json'
    gpu = [output / f'gpu_post_frame_{x.stem.removeprefix("frame_")}.json' for x in captures]
    requirements = [output / n for n in ('cpu_post.json', 'instrumentation.json',
                    'repeatability.json', 'dot4.json')]
    if gpu and all(x.is_file() for x in [*requirements, *gpu, report_a, fsr3, basis]):
        # Important: reuse upstream unchanged source gate, which may return 2.
        add_step(steps, 'unchanged_o0_teacher_gate',
                 [py, str(repo / 'tools/oracles/evaluate_scalar_teacher_gate.py'),
                  '--cpu', str(output / 'cpu_post.json'),
                  '--gpu', *map(str, gpu),
                  '--instrumentation', str(output / 'instrumentation.json'),
                  '--dot4', str(output / 'dot4.json'),
                  '--sequence-report', str(report_a),
                  '--fsr3-report', str(fsr3),
                  '--basis-audit', str(basis),
                  '--repeatability', str(output / 'repeatability.json'),
                  '--output', str(output / 'teacher_gate.json')], repo, logs)
    else:
        steps.append({'name': 'unchanged_o0_teacher_gate', 'passed': False,
                      'required': True, 'error': 'missing prerequisite report; no gate verdict invented',
                      'fsr3_report': str(fsr3), 'basis_audit': str(basis)})
    summary = {'schema': 'f4n10.guarded-o0-execution.v1',
               'arithmetic': args.arithmetic,
               'provider_manifest': str(manifest_path),
               'provider_modes': modes,
               'steps': steps,
               'existing_teacher_gate_passed': any(x['name'] == 'unchanged_o0_teacher_gate'
                                                  and x['passed'] for x in steps),
               'required_steps_all_passed': all(x['passed'] for x in steps if x['required']),
               'note': 'Synthetic-only evidence is never sufficient for game readiness or visual quality.'}
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    print('O0 prerequisite status:', summary['existing_teacher_gate_passed'],
          '; details in', output / 'summary.json')
    return 0 if summary['required_steps_all_passed'] and summary['existing_teacher_gate_passed'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
