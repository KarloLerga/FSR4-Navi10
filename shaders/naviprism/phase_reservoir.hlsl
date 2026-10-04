struct ReservoirEntry
{
    float3 Color;
    float Confidence;
    uint Age;
    float Depth;
    uint Valid;
};

StructuredBuffer<ReservoirEntry> Previous : register(t0);
StructuredBuffer<float2> MotionToPrevious : register(t1);
StructuredBuffer<float> CurrentDepth : register(t2);
StructuredBuffer<uint> CurrentValidity : register(t3);
StructuredBuffer<float4> CurrentColorConfidence : register(t4);

cbuffer ReservoirConstants : register(b0)
{
    uint Width;
    uint Height;
    uint CurrentPhase;
    uint ResetHistory;
    float DepthThreshold;
    float ConfidenceDecay;
    uint MaximumAge;
    uint Padding;
};

RWStructuredBuffer<ReservoirEntry> Next : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 dispatch_thread_id : SV_DispatchThreadID)
{
    const uint pixel = dispatch_thread_id.x;
    const uint pixel_count = Width * Height;
    if (pixel >= pixel_count)
        return;

    const float depth = CurrentDepth[pixel];
    const float2 motion = MotionToPrevious[pixel];
    const float4 current = CurrentColorConfidence[pixel];
    const bool current_map_valid = CurrentValidity[pixel] != 0
        && isfinite(depth) && all(isfinite(motion));

    int2 previous_coordinate = int2(-1, -1);
    if (current_map_valid)
    {
        const float2 rounded = floor(motion + 0.5);
        if (all(rounded >= 0.0) && rounded.x < Width && rounded.y < Height)
            previous_coordinate = int2(rounded);
    }
    const bool previous_coordinate_valid = all(previous_coordinate >= 0);

    for (uint phase = 0; phase < 4; ++phase)
    {
        ReservoirEntry result = (ReservoirEntry)0;
        if (ResetHistory == 0 && current_map_valid && previous_coordinate_valid)
        {
            const uint previous_pixel =
                phase * pixel_count
                + uint(previous_coordinate.y) * Width
                + uint(previous_coordinate.x);
            const ReservoirEntry old = Previous[previous_pixel];
            if (old.Valid != 0 && isfinite(old.Depth)
                && abs(old.Depth - depth) <= DepthThreshold)
            {
                result = old;
                result.Confidence = old.Confidence * ConfidenceDecay;
                result.Age = old.Age >= MaximumAge ? MaximumAge : old.Age + 1;
                result.Depth = depth;
                result.Valid = result.Confidence > 0.0 ? 1 : 0;
            }
        }

        if (phase == CurrentPhase)
        {
            result = (ReservoirEntry)0;
            if (current_map_valid && all(isfinite(current))
                && current.w >= 0.0 && current.w <= 1.0)
            {
                result.Color = current.xyz;
                result.Confidence = current.w;
                result.Age = 0;
                result.Depth = depth;
                result.Valid = 1;
            }
        }

        Next[phase * pixel_count + pixel] = result;
    }
}
