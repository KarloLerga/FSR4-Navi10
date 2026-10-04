# SADNet, Router and Polyphase History

## SADNet role

SADNet is only for low-confidence/hard regions. Do not run full-screen by default.

Hard conditions include low SARM confidence, strong disocclusion, thin alternating detail, reactive regions and unresolved specular behavior.

Adder-like response: y = -sum(abs(x_i-w_i)) + bias.

Quantize weights/activations into logical 0..254 and encode 1..255 for msad4. Preserve identity/detail paths. Prefer predicting correction to THFA output/filter parameters rather than rebuilding RGB from scratch.

Suggested SADNet:
- input current local features + warped-history residual + depth edge + reactive + SARM confidence,
- 2-4 additive residual blocks,
- 8-16 channels,
- output residual/filter/confidence correction.

Benchmark FP16 first/last layers with SAD middle versus fully integer/additive variants.

## Optional binary/logic router

Pack descriptor bits and compare learned prototypes using countbits(sampleBits ^ prototypeBits). Use only for expert selection/hard-easy/history decisions. Keep it only if it beats simple integer hash in real GPU time/quality.

Logic-gate routers are optional experimental candidates only after normal routing works.

## Sparse low-rank experts

If one hard expert is insufficient, route to one specialized expert: thin detail/foliage, specular, disocclusion or reactive. Never evaluate all experts.

## PHR - Polyphase History Reservoir

For exact 2x scale, four LR phase color slices contain the same raw number of color samples as one HR history at equal bytes/sample.

Maintain P00/P10/P01/P11 evidence with confidence, age and optional depth signature. Reproject all slices with refined SARM motion, validate, update the current jitter phase, decay invalid evidence and reconstruct HR from phase evidence plus THFA.

Add bounded history resurrection: one or two persistent snapshots only, match-based selection, bounded memory.

A/B test against normal HR history. Do not ship PHR by default unless quality/performance/memory improves.
