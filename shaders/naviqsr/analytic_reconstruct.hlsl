// GPU AKR validation kernel. Neural controls are supplied by the exported network
// reference path; this shader owns sampling, SPD tap weights, history clipping/blend.
#ifndef TAP_COUNT
#define TAP_COUNT 5
#endif

Texture2D<float4> gCurrentColor : register(t0);
Texture2D<float4> gControls0 : register(t1); // s0, s1, s2, current-alpha logit
Texture2D<float4> gControls1 : register(t2); // clamp, residual gate, detail gain, history confidence
Texture2D<float4> gResidual : register(t3);
Texture2D<float4> gHistory : register(t4);
Texture2D<float2> gMotion : register(t5); // LR-pixel units, current -> previous
Texture2D<float4> gMasks : register(t6); // reactive, transparency, history-valid, unused
RWTexture2D<float4> gOutput : register(u0);
SamplerState gLinearClamp : register(s0);

cbuffer ReconstructionConstants : register(b0)
{
    uint2 gInputSize;
    uint2 gOutputSize;
    float2 gCurrentJitter;
    float2 gPreviousJitter;
};

float Sigmoid(float value)
{
    return 1.0 / (1.0 + exp(-value));
}

float2 TapOffset(uint index)
{
#if TAP_COUNT == 4
    if (index == 0) return float2(1.0, 0.0);
    if (index == 1) return float2(-1.0, 0.0);
    if (index == 2) return float2(0.0, 1.0);
    return float2(0.0, -1.0);
#elif TAP_COUNT == 5
    if (index == 0) return float2(0.0, 0.0);
    if (index == 1) return float2(1.0, 0.0);
    if (index == 2) return float2(-1.0, 0.0);
    if (index == 3) return float2(0.0, 1.0);
    return float2(0.0, -1.0);
#else
    if (index == 0) return float2(1.0, 0.0);
    if (index == 1) return float2(-1.0, 0.0);
    if (index == 2) return float2(0.0, 1.0);
    if (index == 3) return float2(0.0, -1.0);
    if (index == 4) return float2(0.70710678118, 0.70710678118);
    if (index == 5) return float2(-0.70710678118, 0.70710678118);
    if (index == 6) return float2(0.70710678118, -0.70710678118);
    return float2(-0.70710678118, -0.70710678118);
#endif
}

[numthreads(8, 8, 1)]
void main(uint3 dispatchThreadId : SV_DispatchThreadID)
{
    const uint2 pixel = dispatchThreadId.xy;
    if (pixel.x >= gOutputSize.x || pixel.y >= gOutputSize.y)
    {
        return;
    }

    const float2 uv = (float2(pixel) + 0.5) / float2(gOutputSize);
    const float4 c0 = gControls0.SampleLevel(gLinearClamp, uv, 0.0);
    const float4 c1 = gControls1.SampleLevel(gLinearClamp, uv, 0.0);
    const float l11 = exp2(clamp(c0.x, -2.0, 2.0));
    const float l21 = 0.5 * tanh(c0.y);
    const float l22 = exp2(clamp(c0.z, -2.0, 2.0));
    const float q00 = l11 * l11;
    const float q01 = l11 * l21;
    const float q11 = l21 * l21 + l22 * l22;

    float3 weightedColor = 0.0;
    float weightSum = 0.0;
    [unroll]
    for (uint tap = 0; tap < TAP_COUNT; ++tap)
    {
        const float2 offset = TapOffset(tap);
        const float energy = q00 * offset.x * offset.x
                           + 2.0 * q01 * offset.x * offset.y
                           + q11 * offset.y * offset.y;
        const float weight = exp2(clamp(-0.7213475204444817 * energy, -40.0, 0.0));
        const float2 sampleUv = uv + offset / float2(gInputSize);
        weightedColor += gCurrentColor.SampleLevel(gLinearClamp, sampleUv, 0.0).rgb * weight;
        weightSum += weight;
    }
    float3 current = weightedColor / max(weightSum, 1.0e-6);

    const float residualGain = Sigmoid(c1.y) * tanh(c1.z) * 0.1;
    current += gResidual.SampleLevel(gLinearClamp, uv, 0.0).rgb * residualGain;

    const float2 motion = gMotion.SampleLevel(gLinearClamp, uv, 0.0);
    const float2 jitterDelta = gPreviousJitter - gCurrentJitter;
    const float2 historyUv = uv + (motion + jitterDelta) / float2(gInputSize);
    const float3 history = gHistory.SampleLevel(gLinearClamp, historyUv, 0.0).rgb;
    const float3 clipRadius = 0.02 + 0.28 * Sigmoid(c1.x);
    const float3 clippedHistory = clamp(history, current - clipRadius, current + clipRadius);

    const float4 masks = gMasks.SampleLevel(gLinearClamp, uv, 0.0);
    const float historyValidity = saturate(masks.z)
                                * (1.0 - saturate(masks.x))
                                * (1.0 - 0.8 * saturate(masks.y));
    const float historyContribution = (1.0 - Sigmoid(c0.w))
                                    * Sigmoid(c1.w)
                                    * historyValidity;
    const float3 outputColor = lerp(current, clippedHistory, historyContribution);
    gOutput[pixel] = float4(outputColor, 1.0);
}
