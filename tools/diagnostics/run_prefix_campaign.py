#!/usr/bin/env python3
"""Automate fresh-process stateful FSR4 scratch / prefix runs on Windows.

This is diagnostic evidence, never a quality or teacher acceptance criterion.
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
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run_campaign(harness: Path, sequence: Path, output: Path, seeds: list[str],
                 max_pass: int, repeats: int, timeout: int, trace_frame: int,
                 variant: str) -> dict:
    if max_pass not in range(13) or repeats < 2:
        raise ValueError("max_pass must be 0..12; repeats must be >=2")
    if not harness.is_file() or not sequence.is_file():
        raise FileNotFoundError("Missing harness or sequence")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in seeds:
        if seed not in ("off", "zero", "a5", "5a", "ones"):
            raise ValueError(f"Unknown scratch initialization {seed}")
        for final_pass in [None, *range(max_pass + 1)]:
            name = "full" if final_pass is None else f"pass_{final_pass:02d}"
            for repeat in range(1, repeats + 1):
                run_dir = output / f"seed_{seed}" / name / f"run_{repeat}"
                run_dir.mkdir(parents=True, exist_ok=True)
                report_file = run_dir / "sequence.json"
                env = os.environ.copy()
                env["FSR4N10_SCRATCH_INIT"] = seed
                env["FSR4N10_TRACE_SCRATCH_DIR"] = str(run_dir.resolve())
                env["FSR4N10_TRACE_FRAME"] = str(trace_frame)
                env.pop("MLSR-WMMA", None)
                env.pop("MLSR-WATERMARK", None)
                if final_pass is None:
                    env.pop("FSR4N10_LAST_MODEL_PASS", None)
                else:
                    env["FSR4N10_LAST_MODEL_PASS"] = str(final_pass)
                harness_command = ([sys.executable, str(harness.resolve())]
                                   if harness.suffix.lower() == ".py"
                                   else [str(harness.resolve())])
                cmd = harness_command + ["--run-fsr4-provider-sequence",
                                         str(sequence.resolve()), str(report_file.resolve())]
                print(f"{variant} seed={seed} pass={name} repeat={repeat}", flush=True)
                try:
                    proc = subprocess.run(cmd, env=env, timeout=timeout,
                                          capture_output=True, text=True, errors="replace", check=False)
                    (run_dir / "stdout.txt").write_text(proc.stdout, encoding="utf-8")
                    (run_dir / "stderr.txt").write_text(proc.stderr, encoding="utf-8")
                    exit_code = proc.returncode
                    failure = None
                except subprocess.TimeoutExpired as e:
                    exit_code = None
                    failure = f"timeout after {timeout} seconds: {e}"
                    (run_dir / "timeout.txt").write_text(failure, encoding="utf-8")
                expected = [run_dir / f"frame_{trace_frame}_pass_{'full' if final_pass is None else final_pass}_{context}.bin"
                            for context in ("instrumented", "ordinary")]
                file_meta = {}
                for context, path in zip(("instrumented", "ordinary"), expected):
                    if path.is_file():
                        file_meta[context] = {"path": str(path.resolve()),
                                              "size": path.stat().st_size,
                                              "sha256": sha256(path)}
                input_hashes = []
                if report_file.is_file():
                    try:
                        doc = json.loads(report_file.read_text(encoding="utf-8"))
                        input_hashes = [x.get("input_frame_sha256", "") for x in doc.get("frames", [])]
                        sequence_hash = doc.get("sequence_hash")
                        prefix_flag = doc.get("diagnostic_prefix_only")
                        if final_pass is not None and prefix_flag is not True:
                            failure = "prefix marker not reported; ensure patched diagnostic provider is built"
                    except (ValueError, OSError) as exc:
                        failure = f"Invalid report: {exc}"
                        sequence_hash = None
                else:
                    sequence_hash = None
                if len(file_meta) != 2 and failure is None:
                    failure = "Required scratch snapshots missing"
                if exit_code not in (0, None) and failure is None:
                    failure = f"harness exit {exit_code}"
                rows.append({"seed":seed, "pass":final_pass,"pass_name":name,"repeat":repeat,
                             "report_path":str(report_file.resolve()), "exit_code":exit_code,
                             "error":failure,"files":file_meta,
                             "sequence_hash":sequence_hash,"input_hashes":input_hashes})
                partial={"schema":"f4n10.scratch-campaign.v1", "variant":variant,
                         "harness":str(harness.resolve()),"sequence":str(sequence.resolve()),
                         "repeats":repeats,"trace_frame":trace_frame,"cases":rows}
                (output / "campaign.json").write_text(json.dumps(partial,indent=2)+"\n",encoding="utf-8")
    return partial


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--harness",type=Path,required=True)
    p.add_argument("--sequence",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--seeds",nargs="+",default=["off","zero","a5"])
    p.add_argument("--max-pass",type=int,default=12)
    p.add_argument("--repeats",type=int,default=2)
    p.add_argument("--timeout-seconds",type=int,default=300)
    p.add_argument("--trace-frame",type=int,default=0)
    p.add_argument("--variant",default="standard")
    args=p.parse_args()
    report=run_campaign(args.harness,args.sequence,args.output,args.seeds,args.max_pass,
                        args.repeats,args.timeout_seconds,args.trace_frame,args.variant)
    errors=[r for r in report["cases"] if r["error"]]
    print(f"Completed {len(report['cases'])} diagnostic runs; failures={len(errors)}")
    return 2 if errors else 0

if __name__=="__main__":
    raise SystemExit(main())
