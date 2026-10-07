ByteAddressBuffer SourceColor : register(t0);
ByteAddressBuffer HistoryColor : register(t1);
ByteAddressBuffer Parameters : register(t2);
RWByteAddressBuffer OutputColor : register(u0);

cbuffer Constants : register(b0)
{
    uint RenderWidth;
    uint RenderHeight;
    uint OutputWidth;
    uint OutputHeight;
    float JitterX;
    float JitterY;
    float ExposureValue;
    uint StableTransforms;
};

float4 load4(ByteAddressBuffer bufferValue, uint index)
{
    return asfloat(bufferValue.Load4(index * 16u));
}

void store4(RWByteAddressBuffer bufferValue, uint index, float4 value)
{
    bufferValue.Store4(index * 16u, asuint(value));
}

float3 ApplyMuLaw(float3 value)
{
    return max(0.1174f * log(1.0f + 150.0f * value), 0.0f);
}

float3 RemoveMuLaw(float3 value)
{
    return max((exp(8.51788f * value) - 1.0f) / 150.0f, 0.0f);
}

float StableSigmoid(float x)
{
    const float e = exp(-abs(x));
    return x >= 0.0f ? 1.0f / (1.0f + e) : e / (1.0f + e);
}

float StableTanh(float x)
{
    const float e = exp(-2.0f * abs(x));
    const float t = (1.0f - e) / (1.0f + e);
    return x >= 0.0f ? t : -t;
}

[numthreads(8, 8, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x >= OutputWidth || tid.y >= OutputHeight)
        return;

    const uint outputIndex = tid.y * OutputWidth + tid.x;
    const float4 p = load4(Parameters, outputIndex);

    float rho;
    float sx;
    float sy;
    float blend;
    if (StableTransforms != 0u)
    {
        rho = StableTanh(p.x);
        sx = 2.0f * StableSigmoid(p.y);
        sy = 2.0f * StableSigmoid(p.z);
        blend = StableSigmoid(p.w);
    }
    else
    {
        rho = (exp(p.x) - exp(-p.x)) / (exp(p.x) + exp(-p.x));
        sx = 2.0f / (1.0f + exp(-p.y));
        sy = 2.0f / (1.0f + exp(-p.z));
        blend = 1.0f / (1.0f + exp(-p.w));
    }

    const float2 scale = float2((float)OutputWidth / (float)RenderWidth,
                                (float)OutputHeight / (float)RenderHeight);
    const float2 invScale = 1.0f / scale;
    const float2 lrPos =
        (-0.5f + invScale / 2.0f + float2(tid.xy) * invScale)
        + float2(JitterX, JitterY);
    const int2 center = int2(round(lrPos));

    float totalWeight = 0.0f;
    float3 weightedColor = 0.0f.xxx;
    const float kernelFactor = -0.5f / (0.47f * 0.47f);
    const float sx2 = sx * sx;
    const float sy2 = sy * sy;
    const float sxy = sx * sy;

    [unroll]
    for (uint dy = 0u; dy < 3u; ++dy)
    {
        [unroll]
        for (uint dx = 0u; dx < 3u; ++dx)
        {
            // Match upstream's uint sample-coordinate arithmetic. At the left/top
            // edge the coordinate wraps before its float conversion; LoadInputColor
            // reinterprets it as int and clamps only the texel lookup.
            const uint2 rawSample = uint2(center) + uint2(dx, dy) - 1u;
            const int2 loadSample = clamp(int2(rawSample), int2(0, 0),
                                          int2((int)RenderWidth - 1, (int)RenderHeight - 1));
            const float2 dist = (float2(rawSample) - lrPos) * scale;
            const float exponent = kernelFactor *
                (dist.x * dist.x * sx2
                 + 2.0f * rho * dist.x * dist.y * sxy
                 + dist.y * dist.y * sy2);
            const float w = exp(exponent);
            totalWeight += w;
            const uint sourceIndex = (uint)loadSample.y * RenderWidth + (uint)loadSample.x;
            weightedColor += ApplyMuLaw(load4(SourceColor, sourceIndex).rgb * ExposureValue) * w;
        }
    }

    const float3 current = weightedColor / totalWeight;
    const float3 history = load4(HistoryColor, outputIndex).rgb;
    const float3 modelColor = current * (1.0f - blend) + history * blend;
    const float3 finalColor = clamp(RemoveMuLaw(modelColor) / ExposureValue, 0.0f, 64000.0f);
    store4(OutputColor, outputIndex, float4(finalColor, 1.0f));
}
