# Full FSR4 Compatibility Path - Next Work

The new Param4/Delta4 work does not cancel the full FSR4 path.

## 1. First build the exact GPU teacher

This benefits both compatibility and distillation.

## 2. Then implement full FP16 body

Current repo has parameter extraction but no complete runtime FP16 body.

The FP16 compatibility path should remain numerically conservative first.

## 3. Prioritize measured hot passes

From current I8 model timing, focus first on:

- pass 11,
- pass 9,
- pass 13/post,
- pass 2,
- pass 1,
- pass 12.

Do not optimize all passes equally.

## 4. Compare optimized upstream PRE/POST scheduling

The upstream provider has dedicated PRE and POST shaders that combine temporal/image work with model boundary work.

Current separate generated-pass timing is not the final architecture.

Measure the real provider-style path before attributing cost.

## 5. Pass-level FP16 candidate rules

For each pass:

- direct packed FP16,
- prepacked weights,
- fused bias/activation/residual,
- avoid intermediate quant/dequant when compatibility mode permits,
- direct vs alternate convolution implementation,
- wave32/wave64,
- workgroup variants,
- LDS/register tradeoff.

Select by actual Navi10 timestamp and quality/numeric gate.

## 6. Keep exact and high-precision modes separate

`full_fsr4_fp16_compat`
- reproduces original quantization semantics where required.

`full_fsr4_fp16_highprecision`
- removes selected quantization boundaries only after temporal quality tests.

Do not silently mix them.

## 7. Param4/Delta4 work can inform full-model optimization

Teacher-control analysis can reveal whether some full-model passes are primarily predicting smooth controls.

If a full-model approximation is ever proposed, it must be a separately named approximate mode, never the compatibility path.
