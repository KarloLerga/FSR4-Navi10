#!/usr/bin/env python3
"""Pagewise scratch fingerprints and earliest divergent neural-pass prefix.

Different bytes in an *unwritten* or uninitialized buffer are not treated as
valid neural differences: the report separates unseeded from seeded evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

PAGE=4096


def compare_bytes(a: Path, b: Path) -> dict:
    aa=np.memmap(a,dtype=np.uint8,mode="r")
    bb=np.memmap(b,dtype=np.uint8,mode="r")
    if len(aa)!=len(bb):
        return {"equal":False,"size_mismatch":[len(aa),len(bb)]}
    changed=aa!=bb
    count=int(np.count_nonzero(changed))
    pages=[]
    for offset in range(0,len(aa),PAGE):
        n=int(np.count_nonzero(changed[offset:offset+PAGE]))
        if n:pages.append({"index":offset//PAGE,"changed_bytes":n})
    positions=np.flatnonzero(changed)
    return {"equal":count==0,"size":len(aa),"changed_bytes":count,
            "changed_fraction":count/max(1,len(aa)),
            "first_changed_offset":int(positions[0]) if len(positions) else None,
            "changed_page_count":len(pages),"first_changed_pages":pages[:16]}


def analyze_campaign(doc:dict)->dict:
    cases=doc.get("cases",[])
    grouped={}
    for case in cases:
        k=(case["seed"],case["pass_name"])
        grouped.setdefault(k,{})[int(case["repeat"])]=case
    findings=[]
    for (seed,pname),reps in sorted(grouped.items(), key=lambda v:(v[0][0], v[0][1])):
        if 1 not in reps or 2 not in reps:continue
        r1,r2=reps[1],reps[2]
        if r1.get("error") or r2.get("error"):
            findings.append({"seed":seed,"pass_name":pname,"error":"one or both runs failed"})
            continue
        if r1.get("sequence_hash") != r2.get("sequence_hash") or r1.get("input_hashes") != r2.get("input_hashes"):
            findings.append({"seed":seed,"pass_name":pname,"error":"input provenance mismatch"})
            continue
        item={"seed":seed,"pass_name":pname,"repeat_comparison":{},"instrumentation_comparison":{}}
        for context in ("instrumented","ordinary"):
            a=Path(r1["files"][context]["path"])
            b=Path(r2["files"][context]["path"])
            if not a.is_file() or not b.is_file():
                raise FileNotFoundError(f"Scratch snapshot missing: {a} or {b}")
            item["repeat_comparison"][context]=compare_bytes(a,b)
        for n,rep in (("run_1",r1),("run_2",r2)):
            a=Path(rep["files"]["instrumented"]["path"])
            b=Path(rep["files"]["ordinary"]["path"])
            item["instrumentation_comparison"][n]=compare_bytes(a,b)
        findings.append(item)

    first_by_seed={}
    for seed in sorted({c["seed"] for c in cases}):
        prefix=[]
        for f in findings:
            if f.get("seed")!=seed or not f["pass_name"].startswith("pass_") or f.get("error"):
                continue
            i=int(f["pass_name"].split("_")[1])
            mismatched=any(not x["equal"] for x in f["repeat_comparison"].values())
            parity=any(not x["equal"] for x in f["instrumentation_comparison"].values())
            prefix.append((i,mismatched,parity))
        prefix.sort()
        first_by_seed[seed]={
            "first_repeat_divergent_prefix":next((i for i,d,_ in prefix if d),None),
            "first_instrumented_vs_ordinary_divergent_prefix":next((i for i,_,d in prefix if d),None),
            "compared_prefixes":[i for i,_,_ in prefix],
        }
    # Cross-seed comparison is meaningful for final RGB but NOT for raw
    # ScratchBuffer: untouched seeded scratch bytes are expected to differ.
    full_by_seed={}
    for (seed,pname),reps in grouped.items():
        if pname == "full" and 1 in reps and not reps[1].get("error"):
            try:
                full_by_seed[seed]=json.loads(Path(reps[1]["report_path"]).read_text(encoding="utf-8"))
            except (ValueError,OSError,KeyError):
                pass
    # Full 8-frame RGB repeatability is stronger evidence than scratch alone.
    full_rgb_repeatability={}
    for (seed,pname),reps in grouped.items():
        if pname!="full" or 1 not in reps or 2 not in reps:
            continue
        try:
            r1=json.loads(Path(reps[1]["report_path"]).read_text(encoding="utf-8"))
            r2=json.loads(Path(reps[2]["report_path"]).read_text(encoding="utf-8"))
        except (OSError,ValueError,KeyError):
            continue
        f1,f2=r1.get("frames",[]),r2.get("frames",[])
        paired=len(f1)==len(f2) and bool(f1)
        input_equal=paired and all(a.get("input_frame_sha256")==b.get("input_frame_sha256") for a,b in zip(f1,f2))
        ordinary_equal=paired and all(a.get("reference_output_sha256")==b.get("reference_output_sha256") for a,b in zip(f1,f2))
        instrumented_equal=paired and all(a.get("instrumented_output_sha256")==b.get("instrumented_output_sha256") for a,b in zip(f1,f2))
        full_scratch = next((x for x in findings
                             if x.get("seed") == seed and x.get("pass_name") == "full"), None)
        if full_scratch is not None and not full_scratch.get("error"):
            full_scratch_equal = {
                context: comparison["equal"]
                for context, comparison in full_scratch["repeat_comparison"].items()
            }
        else:
            full_scratch_equal = {}
        full_rgb_repeatability[seed]={"frame_count":len(f1),"inputs_equal":input_equal,
            "ordinary_full_rgb_repeatable":ordinary_equal,
            "instrumented_full_rgb_repeatable":instrumented_equal,
            "full_scratch_repeatable":full_scratch_equal}

    cross_seed={}
    for seed in ("zero","a5","5a","ones"):
        if seed not in full_by_seed or "zero" not in full_by_seed or seed=="zero":
            continue
        zero=full_by_seed["zero"]
        other=full_by_seed[seed]
        pairs=[]
        for f0,f1 in zip(zero.get("frames",[]),other.get("frames",[])):
            same_input=f0.get("input_frame_sha256")==f1.get("input_frame_sha256")
            pairs.append({"frame":f0.get("frame_index"),"inputs_equal":same_input,
                          "reference_rgb_hash_equal":f0.get("reference_output_sha256")==f1.get("reference_output_sha256"),
                          "instrumented_rgb_hash_equal":f0.get("instrumented_output_sha256")==f1.get("instrumented_output_sha256")})
        cross_seed[f"zero_vs_{seed}"]={"pairs":pairs,
            "all_inputs_equal":all(x["inputs_equal"] for x in pairs),
            "all_reference_rgb_equal":bool(pairs) and all(x["reference_rgb_hash_equal"] for x in pairs)}
    conclusion=[]
    if any(x["all_inputs_equal"] and not x["all_reference_rgb_equal"] for x in cross_seed.values()):
        conclusion.append("Different scratch fill patterns change ordinary full-provider RGB despite identical inputs: investigate a read-before-write or seed-dependent scratch path.")
    for seed,full_rgb in full_rgb_repeatability.items():
        prefix=first_by_seed.get(seed,{})
        if (full_rgb["inputs_equal"] and not full_rgb["ordinary_full_rgb_repeatable"]
            and prefix.get("first_repeat_divergent_prefix") is None):
            tested=prefix.get("compared_prefixes",[])
            max_tested=max(tested) if tested else None
            scratch_equal=full_rgb["full_scratch_repeatable"].get("ordinary")
            if scratch_equal is True and max_tested == 12:
                conclusion.append(f"Seed {seed}: ordinary full RGB differs across runs while frame-0 scratch snapshots after prefix 12 match; investigate history/recurrent/output resources outside scratch and run timing.")
            elif scratch_equal is True:
                conclusion.append(f"Seed {seed}: ordinary full RGB differs across runs while frame-0 scratch matches through tested prefix {max_tested}; later untested passes and resources outside scratch remain candidates.")
            elif scratch_equal is False and max_tested is not None and max_tested < 12:
                conclusion.append(f"Seed {seed}: ordinary full RGB and full-model scratch differ across runs, while prefixes through {max_tested} match; extend the prefix range before localizing the divergence.")
            elif scratch_equal is False:
                conclusion.append(f"Seed {seed}: ordinary full RGB and full-model scratch differ across runs despite no repeat divergence in the tested pass prefixes; inspect the prefix-12/full boundary and non-scratch state.")
            else:
                conclusion.append(f"Seed {seed}: ordinary full RGB differs across runs, but full scratch repeatability could not be evaluated; inspect the campaign records.")
    if first_by_seed.get("zero",{}).get("first_repeat_divergent_prefix") is not None:
        conclusion.append("Seeded-zero scratch still diverges: uninitialized scratch alone is insufficient to explain repeatability.")
    if first_by_seed.get("zero",{}).get("first_repeat_divergent_prefix") is None and first_by_seed.get("off",{}).get("first_repeat_divergent_prefix") is not None:
        conclusion.append("Unseeded runs diverge while seeded-zero prefixes do not: investigate read-before-write of scratch before accepting causality.")
    if not conclusion:
        conclusion.append("No definitive root cause established; inspect per-pass differences and global-barrier comparison.")
    return {"schema":"f4n10.scratch-campaign-analysis.v1",
            "variant":doc.get("variant"),"first_by_seed":first_by_seed,
            "warnings":["Prefix scratch is observed after POST and may include POST writes.",
                        "Checksum parity of final RGB and real-scene validation remain independent O0 gates.",
                        "A match of scratch prefixes is necessary but not sufficient for a valid FSR4 teacher."],
            "cross_seed_full_rgb":cross_seed,"full_rgb_repeatability":full_rgb_repeatability,
            "interpretation":conclusion,"results":findings}


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign",type=Path)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    doc=json.loads(args.campaign.read_text(encoding="utf-8"))
    report=analyze_campaign(doc)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"first_by_seed":report["first_by_seed"],"interpretation":report["interpretation"]},indent=2))
    return 0 if report["results"] else 2

if __name__=="__main__":
    raise SystemExit(main())
