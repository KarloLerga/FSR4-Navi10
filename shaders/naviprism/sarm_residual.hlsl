StructuredBuffer<uint> CurrentLuma : register(t0);
StructuredBuffer<uint> HistoryLuma : register(t1);
StructuredBuffer<int2> EngineMotion : register(t2);

cbuffer SarmConstants : register(b0)
{
    uint ImageWidth;
    uint ImageHeight;
    uint TileCountX;
    uint TileCountY;
};

struct SarmOutput
{
    float2 ResidualMotion;
    float2 RefinedMotion;
    float Confidence;
    uint BestCost;
    uint SecondCost;
    uint Valid;
};

RWStructuredBuffer<SarmOutput> Results : register(u0);

#define SARM_ROOT_SIGNATURE \
    "DescriptorTable(SRV(t0)),DescriptorTable(SRV(t1)),DescriptorTable(SRV(t2))," \
    "CBV(b0),DescriptorTable(UAV(u0))"

static const int PatchSize = 4;
static const int SearchX = 3;
static const int SearchY = 2;
static const uint InvalidCost = 0xffffffff;

uint read_current(int x, int y)
{
    if (x < 0 || y < 0 || x >= (int)ImageWidth || y >= (int)ImageHeight)
        return 0;
    return CurrentLuma[(uint)y * ImageWidth + (uint)x] & 0xff;
}

uint read_history(int x, int y)
{
    if (x < 0 || y < 0 || x >= (int)ImageWidth || y >= (int)ImageHeight)
        return 0;
    return HistoryLuma[(uint)y * ImageWidth + (uint)x] & 0xff;
}

uint pack_current_row(int x, int y)
{
    return read_current(x + 0, y)
        | (read_current(x + 1, y) << 8)
        | (read_current(x + 2, y) << 16)
        | (read_current(x + 3, y) << 24);
}

uint2 pack_history_span(int x, int y)
{
    return uint2(
        read_history(x + 0, y) | (read_history(x + 1, y) << 8)
            | (read_history(x + 2, y) << 16) | (read_history(x + 3, y) << 24),
        read_history(x + 4, y) | (read_history(x + 5, y) << 8)
            | (read_history(x + 6, y) << 16) | (read_history(x + 7, y) << 24));
}

bool candidate_in_bounds(int x, int y)
{
    return x >= 0 && y >= 0
        && x + PatchSize <= (int)ImageWidth
        && y + PatchSize <= (int)ImageHeight;
}

float quadratic_offset(uint minus_cost, uint center_cost, uint plus_cost)
{
    const float curvature = (float)minus_cost - 2.0 * (float)center_cost
        + (float)plus_cost;
    if (curvature <= 1.0e-6)
        return 0.0;
    return clamp(0.5 * ((float)minus_cost - (float)plus_cost) / curvature,
                 -0.5, 0.5);
}

[numthreads(8, 8, 1)]
[RootSignature(SARM_ROOT_SIGNATURE)]
void main(uint3 dispatch_thread_id : SV_DispatchThreadID)
{
    const uint tile_x = dispatch_thread_id.x;
    const uint tile_y = dispatch_thread_id.y;
    if (tile_x >= TileCountX || tile_y >= TileCountY)
        return;

    const uint output_index = tile_y * TileCountX + tile_x;
    const int patch_x = (int)(tile_x * 8) + 2;
    const int patch_y = (int)(tile_y * 8) + 2;
    SarmOutput output;
    output.ResidualMotion = 0.0;
    output.RefinedMotion = (float2)EngineMotion[output_index];
    output.Confidence = 0.0;
    output.BestCost = InvalidCost;
    output.SecondCost = InvalidCost;
    output.Valid = 0;

    if (!candidate_in_bounds(patch_x, patch_y))
    {
        Results[output_index] = output;
        return;
    }

    const int2 engine = EngineMotion[output_index];
    uint costs[(SearchY * 2 + 1) * (SearchX * 2 + 1)];
    uint valid_reference_samples = 0;
    [unroll]
    for (int row = 0; row < PatchSize; ++row)
    {
        const uint reference = pack_current_row(patch_x, patch_y + row);
        [unroll]
        for (uint column = 0; column < PatchSize; ++column)
        {
            if (((reference >> (column * 8)) & 0xff) != 0)
                ++valid_reference_samples;
        }
    }
    if (valid_reference_samples == 0)
    {
        Results[output_index] = output;
        return;
    }

    [unroll]
    for (uint cost_index = 0; cost_index < (SearchY * 2 + 1) * (SearchX * 2 + 1);
         ++cost_index)
        costs[cost_index] = InvalidCost;

    [loop]
    for (int residual_y = -SearchY; residual_y <= SearchY; ++residual_y)
    {
        uint4 left_costs = 0;
        uint4 right_costs = 0;
        [unroll]
        for (int row = 0; row < PatchSize; ++row)
        {
            const uint reference = pack_current_row(patch_x, patch_y + row);
            const int history_y = patch_y + engine.y + residual_y + row;
            left_costs = msad4(reference,
                pack_history_span(patch_x + engine.x - SearchX, history_y), left_costs);
            right_costs = msad4(reference,
                pack_history_span(patch_x + engine.x + 1, history_y), right_costs);
        }

        [unroll]
        for (int lane = 0; lane < 4; ++lane)
        {
            const int left_dx = lane - SearchX;
            const int left_x = patch_x + engine.x + left_dx;
            if (candidate_in_bounds(left_x, patch_y + engine.y + residual_y))
                costs[(residual_y + SearchY) * (SearchX * 2 + 1)
                    + (left_dx + SearchX)] = left_costs[lane];

            const int right_dx = lane + 1;
            const int right_x = patch_x + engine.x + right_dx;
            if (right_dx <= SearchX
                && candidate_in_bounds(right_x, patch_y + engine.y + residual_y))
                costs[(residual_y + SearchY) * (SearchX * 2 + 1)
                    + (right_dx + SearchX)] = right_costs[lane];
        }
    }

    uint best_cost = InvalidCost;
    uint second_cost = InvalidCost;
    int best_dx = 0;
    int best_dy = 0;
    [unroll]
    for (int dy = -SearchY; dy <= SearchY; ++dy)
    {
        [unroll]
        for (int dx = -SearchX; dx <= SearchX; ++dx)
        {
            const uint cost = costs[(dy + SearchY) * (SearchX * 2 + 1)
                + (dx + SearchX)];
            if (cost < best_cost)
            {
                second_cost = best_cost;
                best_cost = cost;
                best_dx = dx;
                best_dy = dy;
            }
            else if (cost < second_cost)
            {
                second_cost = cost;
            }
        }
    }
    if (best_cost == InvalidCost)
    {
        Results[output_index] = output;
        return;
    }
    if (second_cost == InvalidCost)
        second_cost = best_cost;

    const float uniqueness = (float)(second_cost - best_cost)
        / max((float)second_cost, 1.0);
    const float quality = saturate(1.0 - (float)best_cost
        / ((float)valid_reference_samples * 254.0));
    const float confidence = uniqueness * quality;

    float2 residual = float2((float)best_dx, (float)best_dy);
    if (confidence > 0.0)
    {
        if (best_dx > -SearchX && best_dx < SearchX)
        {
            const uint minus_cost = costs[(best_dy + SearchY) * (SearchX * 2 + 1)
                + (best_dx - 1 + SearchX)];
            const uint plus_cost = costs[(best_dy + SearchY) * (SearchX * 2 + 1)
                + (best_dx + 1 + SearchX)];
            if (minus_cost != InvalidCost && plus_cost != InvalidCost)
                residual.x += quadratic_offset(minus_cost, best_cost, plus_cost);
        }
        if (best_dy > -SearchY && best_dy < SearchY)
        {
            const uint minus_cost = costs[(best_dy - 1 + SearchY) * (SearchX * 2 + 1)
                + (best_dx + SearchX)];
            const uint plus_cost = costs[(best_dy + 1 + SearchY) * (SearchX * 2 + 1)
                + (best_dx + SearchX)];
            if (minus_cost != InvalidCost && plus_cost != InvalidCost)
                residual.y += quadratic_offset(minus_cost, best_cost, plus_cost);
        }
    }

    output.ResidualMotion = residual;
    output.RefinedMotion = (float2)engine + residual;
    output.Confidence = confidence;
    output.BestCost = best_cost;
    output.SecondCost = second_cost;
    output.Valid = 1;
    Results[output_index] = output;
}
