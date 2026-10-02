ByteAddressBuffer InputValues : register(t0);
RWByteAddressBuffer OutputValues : register(u0);

[numthreads(64, 1, 1)]
void main(uint3 dispatchThreadId : SV_DispatchThreadID)
{
    const uint index = dispatchThreadId.x;
    const uint packedInputs = InputValues.Load(index * 4);
    const float16_t left = (float16_t)f16tof32(packedInputs & 0xffff);
    const float16_t right = (float16_t)f16tof32(packedInputs >> 16);
    const float16_t product = left * right;
    OutputValues.Store(index * 4, f32tof16((float)product));
}
