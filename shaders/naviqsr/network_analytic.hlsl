StructuredBuffer<float> Features : register(t0);
StructuredBuffer<float> Controls : register(t1);
StructuredBuffer<float> Residual : register(t2);
StructuredBuffer<float> History : register(t3);
RWStructuredBuffer<float> Output : register(u0);

cbuffer Parameters : register(b0)
{
    uint Width;
    uint Height;
    uint Scale;
    uint OutputWidth;
    uint OutputHeight;
    uint TapCount;
    uint HistoryValid;
    uint Padding;
    float CurrentJitterX;
    float CurrentJitterY;
    float PreviousJitterX;
    float PreviousJitterY;
};

float sample_feature(uint channel, float x, float y)
{
    x = clamp(x, 0.0, float(Width - 1));
    y = clamp(y, 0.0, float(Height - 1));
    const uint x0 = uint(floor(x));
    const uint y0 = uint(floor(y));
    const uint x1 = min(x0 + 1, Width - 1);
    const uint y1 = min(y0 + 1, Height - 1);
    const float fx = x - float(x0);
    const float fy = y - float(y0);
    const uint area = Width * Height;
    const uint base = channel * area;
    const float a = lerp(Features[base + y0 * Width + x0],
                         Features[base + y0 * Width + x1], fx);
    const float b = lerp(Features[base + y1 * Width + x0],
                         Features[base + y1 * Width + x1], fx);
    return lerp(a, b, fy);
}

float sample_control(uint channel, float x, float y)
{
    const uint control_width = Width / 2;
    const uint control_height = Height / 2;
    x = clamp(x, 0.0, float(control_width - 1));
    y = clamp(y, 0.0, float(control_height - 1));
    const uint x0 = uint(floor(x));
    const uint y0 = uint(floor(y));
    const uint x1 = min(x0 + 1, control_width - 1);
    const uint y1 = min(y0 + 1, control_height - 1);
    const float fx = x - float(x0);
    const float fy = y - float(y0);
    const uint area = control_width * control_height;
    const uint base = channel * area;
    const float a = lerp(Controls[base + y0 * control_width + x0],
                         Controls[base + y0 * control_width + x1], fx);
    const float b = lerp(Controls[base + y1 * control_width + x0],
                         Controls[base + y1 * control_width + x1], fx);
    return lerp(a, b, fy);
}

float sample_residual(uint channel, float x, float y)
{
    const uint control_width = Width / 2;
    const uint control_height = Height / 2;
    x = clamp(x, 0.0, float(control_width - 1));
    y = clamp(y, 0.0, float(control_height - 1));
    const uint x0 = uint(floor(x));
    const uint y0 = uint(floor(y));
    const uint x1 = min(x0 + 1, control_width - 1);
    const uint y1 = min(y0 + 1, control_height - 1);
    const float fx = x - float(x0);
    const float fy = y - float(y0);
    const uint area = control_width * control_height;
    const uint base = channel * area;
    const float a = lerp(Residual[base + y0 * control_width + x0],
                         Residual[base + y0 * control_width + x1], fx);
    const float b = lerp(Residual[base + y1 * control_width + x0],
                         Residual[base + y1 * control_width + x1], fx);
    return lerp(a, b, fy);
}

float sample_history(uint channel, float x, float y)
{
    x = clamp(x, 0.0, float(OutputWidth - 1));
    y = clamp(y, 0.0, float(OutputHeight - 1));
    const uint x0 = uint(floor(x));
    const uint y0 = uint(floor(y));
    const uint x1 = min(x0 + 1, OutputWidth - 1);
    const uint y1 = min(y0 + 1, OutputHeight - 1);
    const float fx = x - float(x0);
    const float fy = y - float(y0);
    const uint area = OutputWidth * OutputHeight;
    const uint base = channel * area;
    const float a = lerp(History[base + y0 * OutputWidth + x0],
                         History[base + y0 * OutputWidth + x1], fx);
    const float b = lerp(History[base + y1 * OutputWidth + x0],
                         History[base + y1 * OutputWidth + x1], fx);
    return lerp(a, b, fy);
}

float3 sample_current(float x, float y)
{
    return float3(sample_feature(0, x, y),
                  sample_feature(1, x, y),
                  sample_feature(2, x, y));
}

float3 sample_residual3(float x, float y)
{
    return float3(sample_residual(0, x, y),
                  sample_residual(1, x, y),
                  sample_residual(2, x, y));
}

float3 sample_history3(float x, float y)
{
    return float3(sample_history(0, x, y),
                  sample_history(1, x, y),
                  sample_history(2, x, y));
}

[numthreads(64, 1, 1)]
void main(uint3 dispatchThreadId : SV_DispatchThreadID)
{
    const uint pixel = dispatchThreadId.x;
    const uint output_area = OutputWidth * OutputHeight;
    if (pixel >= output_area)
        return;

    const uint x = pixel % OutputWidth;
    const uint y = pixel / OutputWidth;
    const float control_x = (float(x) + 0.5) / float(Scale * 2) - 0.5;
    const float control_y = (float(y) + 0.5) / float(Scale * 2) - 0.5;
    const float p0 = sample_control(0, control_x, control_y);
    const float p1 = sample_control(1, control_x, control_y);
    const float p2 = sample_control(2, control_x, control_y);
    const float p3 = sample_control(3, control_x, control_y);
    const float p4 = sample_control(4, control_x, control_y);
    const float p5 = sample_control(5, control_x, control_y);
    const float p6 = sample_control(6, control_x, control_y);
    const float p7 = sample_control(7, control_x, control_y);

    const float l11 = exp2(clamp(p0, -2.0, 2.0));
    const float l21 = 0.5 * tanh(p1);
    const float l22 = exp2(clamp(p2, -2.0, 2.0));
    const float q00 = l11 * l11;
    const float q01 = l11 * l21;
    const float q11 = l21 * l21 + l22 * l22;
    const float base_x = (float(x) + 0.5) / float(Scale) - 0.5;
    const float base_y = (float(y) + 0.5) / float(Scale) - 0.5;

    static const float2 offsets[9] = {
        float2(0.0, 0.0),
        float2(1.0, 0.0), float2(-1.0, 0.0),
        float2(0.0, 1.0), float2(0.0, -1.0),
        float2(0.70710678, 0.70710678), float2(-0.70710678, 0.70710678),
        float2(0.70710678, -0.70710678), float2(-0.70710678, -0.70710678)
    };
#if TAP_COUNT == 4
    const uint first_tap = 1;
    const uint last_tap = 5;
#elif TAP_COUNT == 5
    const uint first_tap = 0;
    const uint last_tap = 5;
#else
    const uint first_tap = 1;
    const uint last_tap = 9;
#endif
    float3 current = 0.0;
    float weight_sum = 0.0;
    [loop]
    for (uint tap = first_tap; tap < last_tap; ++tap)
    {
        const float2 offset = offsets[tap];
        const float energy = q00 * offset.x * offset.x
                           + 2.0 * q01 * offset.x * offset.y
                           + q11 * offset.y * offset.y;
        const float weight = exp2(clamp(-0.7213475204444817 * energy, -40.0, 0.0));
        current += sample_current(base_x + offset.x, base_y + offset.y) * weight;
        weight_sum += weight;
    }
    current /= max(weight_sum, 1.0e-6);
    const float residual_gain = (1.0 / (1.0 + exp(-p5))) * tanh(p6);
    current += sample_residual3(control_x, control_y) * residual_gain * 0.1;

    if (HistoryValid != 0)
    {
        const float motion_x = sample_feature(4, base_x, base_y);
        const float motion_y = sample_feature(5, base_x, base_y);
        const float reactive = saturate(sample_feature(6, base_x, base_y));
        const float transparency = saturate(sample_feature(7, base_x, base_y));
        const float validity = (1.0 - reactive) * (1.0 - 0.8 * transparency);
        const float clip_radius = 0.02 + 0.28 * (1.0 / (1.0 + exp(-p4)));
        const float3 history = sample_history3(
            float(x) + (motion_x + PreviousJitterX - CurrentJitterX) * float(Scale),
            float(y) + (motion_y + PreviousJitterY - CurrentJitterY) * float(Scale));
        const float3 clipped_history = clamp(history, current - clip_radius, current + clip_radius);
        const float current_alpha = 1.0 / (1.0 + exp(-p3));
        const float confidence = 1.0 / (1.0 + exp(-p7));
        const float history_alpha = saturate(1.0 - (1.0 - current_alpha) * confidence * validity);
        current = current * history_alpha + clipped_history * (1.0 - history_alpha);
    }

    Output[pixel] = current.x;
    Output[output_area + pixel] = current.y;
    Output[2 * output_area + pixel] = current.z;
}
