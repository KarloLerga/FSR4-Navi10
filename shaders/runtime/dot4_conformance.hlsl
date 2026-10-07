RWByteAddressBuffer OutputValues : register(u0);

int sign_extend_i8(uint value)
{
    const uint byteValue = value & 0xffu;
    return (byteValue & 0x80u) != 0u ? int(byteValue) - 256 : int(byteValue);
}

int scalar_dot4add_i8packed(uint a, uint b, int acc)
{
    return acc
        + sign_extend_i8(a) * sign_extend_i8(b)
        + sign_extend_i8(a >> 8) * sign_extend_i8(b >> 8)
        + sign_extend_i8(a >> 16) * sign_extend_i8(b >> 16)
        + sign_extend_i8(a >> 24) * sign_extend_i8(b >> 24);
}

uint hash32(uint x)
{
    x ^= x >> 16;
    x *= 0x7feb352du;
    x ^= x >> 15;
    x *= 0x846ca68bu;
    x ^= x >> 16;
    return x;
}

[numthreads(64, 1, 1)]
void main(uint3 tid : SV_DispatchThreadID)
{
    const uint index = tid.x;
    if (index >= 256u)
        return;

    uint a = hash32(index * 0x9e3779b9u + 0x01234567u);
    uint b = hash32(index * 0x85ebca6bu + 0x07654321u);

    if (index == 0u) { a = 0x00000000u; b = 0x00000000u; }
    if (index == 1u) { a = 0x7f7f7f7fu; b = 0x7f7f7f7fu; }
    if (index == 2u) { a = 0x80808080u; b = 0x01010101u; }
    if (index == 3u) { a = 0xff00ff00u; b = 0x01ff7f80u; }

    const int acc = int(hash32(index ^ 0xa5a5a5a5u) & 0x0001ffffu) - 65536;
    const int nativeResult = dot4add_i8packed(a, b, acc);
    const int scalarResult = scalar_dot4add_i8packed(a, b, acc);

    const uint base = index * 16u;
    OutputValues.Store(base + 0u, asuint(nativeResult));
    OutputValues.Store(base + 4u, asuint(scalarResult));
    OutputValues.Store(base + 8u, a);
    OutputValues.Store(base + 12u, b);
}
