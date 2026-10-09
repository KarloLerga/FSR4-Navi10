"""Build-local Pass 1 arithmetic variants for the pinned FSR4 Native/1080 model.

This module never changes third_party/ source and is never enabled by default.
The native variants are mathematically equivalent under the bounded INT32
accumulation domain of Pass 1; equality on Navi10 is a measured question.
"""
from __future__ import annotations

from pathlib import Path

VARIANTS = (
    'native_zero',
    'native_swap',
    'native_swap_zero',
    'unpack_dot',
    'unpack_scalar',
    'unsigned_bias_3dot',
)

# A compact common signature forces an explicit uint conversion at the macro
# call boundary instead of allowing every call to infer the packed datatype.
# No helper uses floating point. No helper changes model weights or layouts.
HELPERS = {
    'native_zero': '''
int fsr4n10_experimental_dot4(uint a, uint b, int acc)
{
    // Same signed i8 dot, but accumulate outside native DP4A lowering.
    return acc + dot4add_i8packed(a, b, 0);
}
''',
    'native_swap': '''
int fsr4n10_experimental_dot4(uint a, uint b, int acc)
{
    // Signed dot product is commutative; this alters backend operand mapping.
    return dot4add_i8packed(b, a, acc);
}
''',
    'native_swap_zero': '''
int fsr4n10_experimental_dot4(uint a, uint b, int acc)
{
    return acc + dot4add_i8packed(b, a, 0);
}
''',
    'unpack_dot': '''
int fsr4n10_experimental_dot4(uint a, uint b, int acc)
{
    const int4 av = unpack_s8s32((int8_t4_packed)a);
    const int4 bv = unpack_s8s32((int8_t4_packed)b);
    return acc + dot(av, bv);
}
''',
    'unpack_scalar': '''
int fsr4n10_experimental_dot4(uint a, uint b, int acc)
{
    const int4 av = unpack_s8s32((int8_t4_packed)a);
    const int4 bv = unpack_s8s32((int8_t4_packed)b);
    return acc + av.x * bv.x + av.y * bv.y + av.z * bv.z + av.w * bv.w;
}
''',
    'unsigned_bias_3dot': '''
int fsr4n10_experimental_dot4(uint a, uint b, int acc)
{
    // Exact signed-DP4 identity using THREE native unsigned-DP4 operations:
    // signed(x) = unsigned(x XOR 0x80) - 128, per byte.
    // The 4-lane cross term is 4*(128*128) = 65536.
    const uint ax = a ^ 0x80808080u;
    const uint bx = b ^ 0x80808080u;
    const uint product = dot4add_u8packed(ax, bx, 0u);
    const uint suma = dot4add_u8packed(ax, 0x01010101u, 0u);
    const uint sumb = dot4add_u8packed(bx, 0x01010101u, 0u);
    return acc + int(product) - 128 * (int(suma) + int(sumb)) + 65536;
}
''',
}


def make_wrapper(directory: Path, variant: str,
                 model_include: str = 'passes_1080.hlsl') -> Path:
    if variant not in VARIANTS:
        raise ValueError(f'unsupported Pass 1 arithmetic experiment: {variant}')
    if model_include != 'passes_1080.hlsl':
        raise ValueError('refusing a model include outside pinned Native/1080')
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'fsr4n10_pass1_dot4_variant.hlsl'
    body = (
        '// FSR4N10_PASS1_DOT4_EXPERIMENT ' + variant + '\n'
        + HELPERS[variant]
        + '\n#define dot4add_i8packed fsr4n10_experimental_dot4\n'
        + '#include "' + model_include + '"\n'
    )
    path.write_text(body, encoding='utf-8')
    return path
