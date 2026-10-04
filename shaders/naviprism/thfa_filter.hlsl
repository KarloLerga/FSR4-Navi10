#ifndef FILTER_TAPS
#define FILTER_TAPS 9
#endif

StructuredBuffer<float3> CurrentColor : register(t0);
StructuredBuffer<uint> SpatialDescriptors : register(t1);
StructuredBuffer<uint> TemporalDescriptors : register(t2);
StructuredBuffer<uint> PhaseDescriptors : register(t3);
StructuredBuffer<float> SpatialAtlas : register(t4);
StructuredBuffer<float> TemporalAtlas : register(t5);
StructuredBuffer<float> PhaseAtlas : register(t6);

cbuffer ThfaConstants : register(b0)
{
    uint InputWidth;
    uint InputHeight;
    uint OutputWidth;
    uint OutputHeight;
};

RWStructuredBuffer<float3> OutputColor : register(u0);

#define THFA_ROOT_SIGNATURE \
    "DescriptorTable(SRV(t0)),DescriptorTable(SRV(t1)),DescriptorTable(SRV(t2))," \
    "DescriptorTable(SRV(t3)),DescriptorTable(SRV(t4)),DescriptorTable(SRV(t5))," \
    "DescriptorTable(SRV(t6)),CBV(b0),DescriptorTable(UAV(u0))"

static const uint FeatureCount = 10;

float3 load_color(int x, int y)
{
    x = clamp(x, 0, (int)InputWidth - 1);
    y = clamp(y, 0, (int)InputHeight - 1);
    return CurrentColor[(uint)y * InputWidth + (uint)x];
}

bool tap_enabled(uint tap)
{
#if FILTER_TAPS == 4
    return tap == 0 || tap == 2 || tap == 6 || tap == 8;
#elif FILTER_TAPS == 5
    return tap == 1 || tap == 3 || tap == 4 || tap == 5 || tap == 7;
#elif FILTER_TAPS == 8
    return tap != 4;
#else
    return true;
#endif
}

[numthreads(8, 8, 1)]
[RootSignature(THFA_ROOT_SIGNATURE)]
void main(uint3 dispatch_thread_id : SV_DispatchThreadID)
{
    const uint2 output_pixel = dispatch_thread_id.xy;
    if (output_pixel.x >= OutputWidth || output_pixel.y >= OutputHeight)
        return;

    const float2 low_position = ((float2)output_pixel + 0.5) * 0.5 - 0.5;
    const int2 low_base = (int2)floor(low_position);
    const float2 fraction = frac(low_position);
    const float3 top = lerp(load_color(low_base.x, low_base.y),
                            load_color(low_base.x + 1, low_base.y), fraction.x);
    const float3 bottom = lerp(load_color(low_base.x, low_base.y + 1),
                               load_color(low_base.x + 1, low_base.y + 1), fraction.x);
    const float3 baseline = lerp(top, bottom, fraction.y);

    const uint descriptor_x = (uint)clamp(low_base.x, 0, (int)InputWidth - 1);
    const uint descriptor_y = (uint)clamp(low_base.y, 0, (int)InputHeight - 1);
    const uint descriptor_index = descriptor_y * InputWidth + descriptor_x;
    const uint spatial_bucket = SpatialDescriptors[descriptor_index];
    const uint temporal_bucket = TemporalDescriptors[descriptor_index];
    const uint phase_bucket = PhaseDescriptors[descriptor_index];
    const uint spatial_base = spatial_bucket * FeatureCount;
    const uint temporal_base = temporal_bucket * FeatureCount;
    const uint phase_base = phase_bucket * FeatureCount;

    float3 residual = SpatialAtlas[spatial_base]
        + TemporalAtlas[temporal_base] + PhaseAtlas[phase_base];
    const int2 offsets[9] = {
        int2(-1, -1), int2(0, -1), int2(1, -1),
        int2(-1, 0), int2(0, 0), int2(1, 0),
        int2(-1, 1), int2(0, 1), int2(1, 1)
    };
    [unroll]
    for (uint tap = 0; tap < 9; ++tap)
    {
        if (!tap_enabled(tap))
            continue;
        const float3 local = load_color(low_base.x + offsets[tap].x,
                                        low_base.y + offsets[tap].y);
        const float weight = SpatialAtlas[spatial_base + tap + 1]
            + TemporalAtlas[temporal_base + tap + 1]
            + PhaseAtlas[phase_base + tap + 1];
        residual += (local - baseline) * weight;
    }
    OutputColor[output_pixel.y * OutputWidth + output_pixel.x] = baseline + residual;
}
