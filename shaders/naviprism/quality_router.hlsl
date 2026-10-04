struct TileEvidence
{
    float SarmConfidence;
    float Disocclusion;
    uint SarmValid;
    uint ThinDetail;
    uint Reactive;
    uint SpecularRisk;
    uint HistoryValid;
    uint ForceReference;
};

StructuredBuffer<TileEvidence> Evidence : register(t0);
cbuffer RouterConstants : register(b0)
{
    uint TileCount;
};

RWStructuredBuffer<uint> RouteByTile : register(u0);
RWStructuredBuffer<uint> HardTileList : register(u1);
RWStructuredBuffer<uint> VeryHardTileList : register(u2);
RWStructuredBuffer<uint> RouteCounts : register(u3);

#define NAVIPRISM_ROUTER_ROOT_SIGNATURE \
    "DescriptorTable(SRV(t0)),CBV(b0),DescriptorTable(UAV(u0))," \
    "DescriptorTable(UAV(u1)),DescriptorTable(UAV(u2)),DescriptorTable(UAV(u3))"

static const uint RouteEasy = 0;
static const uint RouteMedium = 1;
static const uint RouteHard = 2;
static const uint RouteVeryHard = 3;
static const uint RouteReference = 4;

uint classify_tile(TileEvidence evidence)
{
    if (evidence.ForceReference != 0)
        return RouteReference;
    if (evidence.SarmValid == 0 || evidence.SarmConfidence < 0.20
        || evidence.Disocclusion > 0.75)
        return RouteVeryHard;
    if (evidence.SarmConfidence < 0.55 || evidence.Disocclusion > 0.15
        || evidence.ThinDetail != 0 || evidence.Reactive != 0
        || evidence.SpecularRisk != 0 || evidence.HistoryValid == 0)
        return RouteHard;
    if (evidence.SarmConfidence < 0.85 || evidence.Disocclusion > 0.05)
        return RouteMedium;
    return RouteEasy;
}

[numthreads(64, 1, 1)]
[RootSignature(NAVIPRISM_ROUTER_ROOT_SIGNATURE)]
void main(uint3 dispatch_thread_id : SV_DispatchThreadID)
{
    const uint tile = dispatch_thread_id.x;
    if (tile >= TileCount)
        return;
    const uint route = classify_tile(Evidence[tile]);
    RouteByTile[tile] = route;
    uint route_slot = 0;
    InterlockedAdd(RouteCounts[route], 1, route_slot);
    if (route == RouteHard)
        HardTileList[route_slot] = tile;
    else if (route == RouteVeryHard)
        VeryHardTileList[route_slot] = tile;
}
