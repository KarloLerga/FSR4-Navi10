StructuredBuffer<float> Luma : register(t0);
StructuredBuffer<float> MotionMagnitude : register(t1);
StructuredBuffer<float> SarmConfidence : register(t2);
StructuredBuffer<uint> ReactiveMask : register(t3);
StructuredBuffer<uint> HistoryValid : register(t4);
StructuredBuffer<uint> PhaseInput : register(t5);

cbuffer DescriptorConstants : register(b0)
{
    uint ImageWidth;
    uint ImageHeight;
};

RWStructuredBuffer<uint> SpatialOutput : register(u0);
RWStructuredBuffer<uint> TemporalOutput : register(u1);
RWStructuredBuffer<uint> PhaseOutput : register(u2);

#define THFA_DESCRIPTOR_ROOT_SIGNATURE \
    "DescriptorTable(SRV(t0)),DescriptorTable(SRV(t1)),DescriptorTable(SRV(t2))," \
    "DescriptorTable(SRV(t3)),DescriptorTable(SRV(t4)),DescriptorTable(SRV(t5))," \
    "CBV(b0),DescriptorTable(UAV(u0)),DescriptorTable(UAV(u1)),DescriptorTable(UAV(u2))"

float read_luma(int x, int y)
{
    x = clamp(x, 0, (int)ImageWidth - 1);
    y = clamp(y, 0, (int)ImageHeight - 1);
    return Luma[(uint)y * ImageWidth + (uint)x];
}

uint spatial_bucket(uint2 pixel)
{
    const float tl = read_luma((int)pixel.x - 1, (int)pixel.y - 1);
    const float tc = read_luma((int)pixel.x, (int)pixel.y - 1);
    const float tr = read_luma((int)pixel.x + 1, (int)pixel.y - 1);
    const float ml = read_luma((int)pixel.x - 1, (int)pixel.y);
    const float mc = read_luma((int)pixel.x, (int)pixel.y);
    const float mr = read_luma((int)pixel.x + 1, (int)pixel.y);
    const float bl = read_luma((int)pixel.x - 1, (int)pixel.y + 1);
    const float bc = read_luma((int)pixel.x, (int)pixel.y + 1);
    const float br = read_luma((int)pixel.x + 1, (int)pixel.y + 1);
    const float gx = mr - ml;
    const float gy = bc - tc;
    const float abs_gx = abs(gx);
    const float abs_gy = abs(gy);
    const float magnitude = sqrt(gx * gx + gy * gy);

    uint orientation = 0;
    if (abs_gx < 1.0e-8 && abs_gy < 1.0e-8)
    {
        orientation = 0;
    }
    else if (abs_gx < 1.0e-8)
    {
        orientation = 4;
    }
    else if (abs_gy >= 1.0e-8)
    {
        const float slope = abs_gy / abs_gx;
        uint local_bin = slope < 0.41421357 ? 0
            : slope < 1.0 ? 1 : slope < 2.41421366 ? 2 : 3;
        const bool same_sign = (gx > 0.0) == (gy > 0.0);
        orientation = local_bin + (same_sign ? 0 : 4);
    }

    const uint strength = magnitude < 0.08 ? 0
        : magnitude < 0.25 ? 1 : magnitude < 0.5 ? 2 : 3;
    const float coherence_ratio = abs(abs_gx - abs_gy)
        / max(abs_gx + abs_gy, 1.0e-8);
    const uint coherence = min(3, (uint)(coherence_ratio * 4.0));
    const float checker = abs(tl + br - tr - bl);
    const uint alias_risk = checker > 1.0 ? 1 : 0;
    const float local_min = min(min(min(tl, tc), min(tr, ml)),
                                min(min(mc, mr), min(min(bl, bc), br)));
    const float local_max = max(max(max(tl, tc), max(tr, ml)),
                                max(max(mc, mr), max(max(bl, bc), br)));
    const uint contrast = local_max - local_min > 0.375 ? 1 : 0;
    return ((((orientation * 4 + strength) * 4 + coherence) * 2
             + alias_risk) * 2 + contrast);
}

uint temporal_bucket(uint index)
{
    const float motion = MotionMagnitude[index];
    const uint motion_bin = motion < 1.0 ? 0 : motion < 4.0 ? 1 : 2;
    const uint confidence_bin = min(3, (uint)(saturate(SarmConfidence[index]) * 4.0));
    const uint reactive = ReactiveMask[index] != 0 ? 1 : 0;
    const uint history_valid = HistoryValid[index] != 0 ? 1 : 0;
    return (((motion_bin * 4 + confidence_bin) * 2 + reactive) * 2 + history_valid);
}

[numthreads(8, 8, 1)]
[RootSignature(THFA_DESCRIPTOR_ROOT_SIGNATURE)]
void main(uint3 dispatch_thread_id : SV_DispatchThreadID)
{
    const uint2 pixel = dispatch_thread_id.xy;
    if (pixel.x >= ImageWidth || pixel.y >= ImageHeight)
        return;
    const uint index = pixel.y * ImageWidth + pixel.x;
    SpatialOutput[index] = spatial_bucket(pixel);
    TemporalOutput[index] = temporal_bucket(index);
    PhaseOutput[index] = PhaseInput[index] & 3;
}
