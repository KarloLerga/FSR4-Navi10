struct MsadInput
{
    uint Reference;
    uint SourceLow;
    uint SourceHigh;
    uint Padding;
};

StructuredBuffer<MsadInput> Inputs : register(t0);
RWStructuredBuffer<uint4> Outputs : register(u0);

#define NAVIPRISM_ROOT_SIGNATURE "DescriptorTable(SRV(t0)),DescriptorTable(UAV(u0))"

static const uint CaseCount = 4096;
static const uint SamplesPerChunk = 48;
static const uint ChunkCount = 2;

uint source_byte(uint source_low, uint source_high, uint index)
{
    const uint word = index < 4 ? source_low : source_high;
    return (word >> ((index & 3) * 8)) & 0xff;
}

[numthreads(64, 1, 1)]
[RootSignature(NAVIPRISM_ROOT_SIGNATURE)]
void main(uint3 dispatch_thread_id : SV_DispatchThreadID)
{
    const uint case_index = dispatch_thread_id.x;
    if (case_index >= CaseCount)
        return;

    uint4 total = 0;
    [loop]
    for (uint chunk = 0; chunk < ChunkCount; ++chunk)
    {
#if MSAD_MODE == 2
        // Keep the byte subtraction in FP16, then accumulate exactly in FP32.
        // Repeated FP16 additions lose multiple byte counts at this workload size.
        float4 partial = 0;
#else
        uint4 partial = 0;
#endif
        [loop]
        for (uint sample = 0; sample < SamplesPerChunk; ++sample)
        {
            const MsadInput input = Inputs[
                case_index * (SamplesPerChunk * ChunkCount)
                + chunk * SamplesPerChunk + sample];
#if MSAD_MODE == 0
            partial = msad4(input.Reference,
                            uint2(input.SourceLow, input.SourceHigh), partial);
#else
            [unroll]
            for (uint alignment = 0; alignment < 4; ++alignment)
            {
                [unroll]
                for (uint reference_index = 0; reference_index < 4; ++reference_index)
                {
                    const uint reference_byte =
                        (input.Reference >> (reference_index * 8)) & 0xff;
                    if (reference_byte == 0)
                        continue;
                    const uint source_value = source_byte(
                        input.SourceLow, input.SourceHigh,
                        alignment + reference_index);
#if MSAD_MODE == 1
                    const uint difference = reference_byte > source_value
                        ? reference_byte - source_value : source_value - reference_byte;
                    partial[alignment] += difference;
#else
                    const float16_t reference_half = (float16_t)reference_byte;
                    const float16_t source_half = (float16_t)source_value;
                    const float16_t difference = abs(reference_half - source_half);
                    partial[alignment] += (float)difference;
#endif
                }
            }
#endif
        }
#if MSAD_MODE == 2
        total += (uint4)partial;
#else
        total += partial;
#endif
    }
    Outputs[case_index] = total;
}
