// Diagnostic only: deterministic initialization of AMD FSR4 I8 scratch buffer.
// The production shader graph and model weights are not modified.
RWByteAddressBuffer ScratchBuffer : register(u0);
cbuffer ScratchFillConstants : register(b0)
{
    uint WordCount;
    uint FillPattern;
};

[numthreads(256, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    if (tid.x < WordCount)
        ScratchBuffer.Store(tid.x * 4u, FillPattern);
}
