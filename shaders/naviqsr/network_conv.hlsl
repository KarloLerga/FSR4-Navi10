StructuredBuffer<float> InputA : register(t0);
StructuredBuffer<float> InputB : register(t1);
ByteAddressBuffer Weights : register(t2);
RWStructuredBuffer<float> Output : register(u0);

cbuffer Parameters : register(b0)
{
    uint Operation;
    uint Width;
    uint Height;
    uint ChannelsA;
    uint ChannelsB;
    uint ChannelsOut;
    uint KernelSize;
    uint WeightOffset;
    uint BiasOffset;
    uint ApplyRelu;
    uint AddResidual;
    uint OutputOffset;
    uint InputBWidth;
    uint InputBHeight;
};

float read_weight(uint index)
{
    const uint pair = Weights.Load((index >> 1) * 4);
    const uint half_bits = (index & 1) != 0 ? pair >> 16 : pair & 0xffff;
    return f16tof32(half_bits);
}

[numthreads(64, 1, 1)]
void main(uint3 dispatchThreadId : SV_DispatchThreadID)
{
    const uint index = dispatchThreadId.x;
    const uint area = Width * Height;
    const uint outputCount = area * ChannelsOut;
    if (index >= outputCount)
        return;

    const uint outputChannel = index / area;
    const uint pixel = index - outputChannel * area;
    const uint x = pixel % Width;
    const uint y = pixel / Width;
    float value = 0.0;

    if (Operation == 1)
    {
        if (outputChannel < ChannelsA)
        {
            value = InputA[outputChannel * area + pixel];
        }
        else
        {
            const uint channelB = outputChannel - ChannelsA;
            const uint x2 = x * 2;
            const uint y2 = y * 2;
            const uint row0 = channelB * InputBWidth * InputBHeight + y2 * InputBWidth + x2;
            value = 0.25 * (InputB[row0] + InputB[row0 + 1]
                          + InputB[row0 + InputBWidth] + InputB[row0 + InputBWidth + 1]);
        }
        Output[OutputOffset + index] = value;
        return;
    }

    value = read_weight(BiasOffset + outputChannel);
    const int radius = int(KernelSize / 2);
    [loop]
    for (uint inputChannel = 0; inputChannel < ChannelsA; ++inputChannel)
    {
        [loop]
        for (uint ky = 0; ky < KernelSize; ++ky)
        {
            const int sourceY = clamp(int(y) + int(ky) - radius, 0, int(Height) - 1);
            [loop]
            for (uint kx = 0; kx < KernelSize; ++kx)
            {
                const int sourceX = clamp(int(x) + int(kx) - radius, 0, int(Width) - 1);
                const uint sourceIndex = inputChannel * area
                                       + uint(sourceY) * Width + uint(sourceX);
                const uint weightIndex = WeightOffset
                    + (((outputChannel * ChannelsA + inputChannel) * KernelSize + ky)
                    * KernelSize + kx);
                value += InputA[sourceIndex] * read_weight(weightIndex);
            }
        }
    }

    if (AddResidual != 0)
        value += InputA[index];
    if (ApplyRelu != 0)
        value = max(value, 0.0);
    Output[OutputOffset + index] = value;
}
