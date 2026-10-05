# FSR3.1.5 aligned capture for Delta4

## Why this is high leverage

FSR3.1.5 is already heavily optimized for temporal upscaling and performs far better than current I8 FSR4 on RX 5700 XT. Delta4 should not recompute temporal semantics FSR3 already owns.

AMD's published RX 5700 XT FSR3.1 timing is useful as a sanity reference, but local sequence timing is authoritative. Published approximate upscale costs include about 4.4 ms at 4K Quality and 3.7 ms at 4K Performance.

## Pin one source/version

Pin exact FSR3.1.5 source and record:
- repository/SDK commit
- shader hashes
- compiler version/flags

Never mix versions under one dataset id.

## Exact input alignment

FSR3 and FSR4 must consume the same:
- input color
- render/output size
- jitter
- motion vectors
- depth
- exposure/pre-exposure
- reactive/T&C validity/content
- reset/cut
- frame time delta
- sequence/frame identity

Pair by hashes, not file naming.

## Capture useful FSR3 temporal semantics

Inspect pinned source before naming resources. Candidate useful signals:
- dilated motion vectors
- dilated depth
- reconstructed previous depth
- current upsampled candidate before final accumulation
- reprojected history before final accumulation
- shading-change factor
- accumulation/confidence
- luma instability
- reactive/dilated reactive state
- locks/new locks
- final FSR3 output

Do not capture every resource blindly. Keep only signals that oracle/ablation proves useful.

## Capture-only correctness

Exactly as with FSR4:
- normal and instrumented FSR3 final output must match
- capture UAVs cannot feed computation
- record shader hashes
- repeat stateful sequences deterministically

## Required basis signals

The Delta basis oracle needs:
- C = current FSR3 reconstruction candidate
- H = reprojected FSR3 history
- T = aligned FSR4 teacher RGB

If C/H are not stable named resources, add capture-only taps at the exact accumulation site.

## Fair runtime accounting

Measure separately:

Scenario A:
`standalone ParamGrid/Param4 total`

Scenario B:
`FSR3 total + Delta4 correction total`

Do not report only correction cost if FSR3 must also execute.

## Required comparison

At identical sequences compare:
- FSR3.1.5
- full FSR4 I8 teacher
- full FSR4 FP16 when ready
- ParamGrid/Param4
- FSR3 + Delta4
- NaviQSR
- final auto/hybrid candidate
