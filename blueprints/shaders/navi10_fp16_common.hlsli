#ifndef FSR4N10_FP16_COMMON_HLSLI
#define FSR4N10_FP16_COMMON_HLSLI

// Blueprint only: Codex must integrate these principles with the actual upstream
// model/operator definitions. Do not treat this as a complete FSR4 operator.

#if !defined(__HLSL_VERSION)
#error HLSL is required
#endif

using f16  = float16_t;
using f16x2 = vector<float16_t, 2>;
using f16x4 = vector<float16_t, 4>;

inline float F16PairDotF32(f16x2 a, f16x2 b)
{
    // Explicit FP32 accumulation is the compatibility-safe baseline.
    return (float)a.x * (float)b.x + (float)a.y * (float)b.y;
}

inline f16x2 F16PairMad(f16x2 a, f16x2 b, f16x2 acc)
{
    return mad(a, b, acc);
}

inline f16 CompatQuantizeDequantize(f16 value, float scale, float bias, float lo, float hi)
{
    // Placeholder semantic blueprint. Replace with the EXACT upstream formula,
    // rounding mode and scale convention extracted from FSR4 source.
    float v = clamp((float)value, lo, hi);
    float q = round(v * scale + bias);
    return (f16)((q - bias) / scale);
}

#endif
