#define FFX_CPU

#include "ffx_internal_types.h"
#include "shader_selector.h"

#include <cstdint>

#include <fsr4_model_v07_i8_native.h>
#include <fsr4_model_v07_i8_native_0_permutations.h>
#include <fsr4_model_v07_i8_native_13_permutations.h>
#include <fsr4_model_v07_i8_native_1080_1_permutations.h>
#include <fsr4_model_v07_i8_native_1080_2_permutations.h>
#include <fsr4_model_v07_i8_native_1080_3_permutations.h>
#include <fsr4_model_v07_i8_native_1080_4_permutations.h>
#include <fsr4_model_v07_i8_native_1080_5_permutations.h>
#include <fsr4_model_v07_i8_native_1080_6_permutations.h>
#include <fsr4_model_v07_i8_native_1080_7_permutations.h>
#include <fsr4_model_v07_i8_native_1080_8_permutations.h>
#include <fsr4_model_v07_i8_native_1080_9_permutations.h>
#include <fsr4_model_v07_i8_native_1080_10_permutations.h>
#include <fsr4_model_v07_i8_native_1080_11_permutations.h>
#include <fsr4_model_v07_i8_native_1080_12_permutations.h>
#include <fsr4_model_v07_i8_native_1080_0_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_1_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_2_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_3_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_4_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_5_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_6_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_7_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_8_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_9_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_10_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_11_post_permutations.h>
#include <fsr4_model_v07_i8_native_1080_12_post_permutations.h>
#include <rcas_permutations.h>
#include <spd_auto_exposure_permutations.h>
#include <debug_view_permutations.h>

#define FSR4N10_ASSIGN_BLOB(_index, _table) \
    POPULATE_SHADER_BLOB_FFX(g_##_table##_PermutationInfo, g_##_table##_IndirectionTable[_index])

namespace {

bool supports_navi10_native_1080(const fsr4_shaders::PermutationOptions& options) {
    return options.preset == fsr4_shaders::Preset::NativeAA &&
           options.maxRes == fsr4_shaders::MaxResolution::Res_1920_1080 && !options.WMMA;
}

uint32_t colorspace(const fsr4_shaders::PermutationOptions& options) {
    if (options.NONLINEAR_COLORSPACE_PQ) {
        return 3;
    }
    if (options.NONLINEAR_COLORSPACE_SRGB) {
        return 2;
    }
    return options.NONLINEAR_COLORSPACE ? 1U : 0U;
}

} // namespace

FfxShaderBlob fsr4_shaders::GetPreShaderBlob(uint32_t permutationOption) {
    const auto options = PermutationOptionsFromKey(permutationOption);
    if (!supports_navi10_native_1080(options)) {
        return {};
    }

    fsr4_model_v07_i8_native_0_PermutationKey key{};
    key.FFX_MLSR_DEPTH_INVERTED = options.DEPTH_INVERTED;
    key.FFX_MLSR_LOW_RES_MV = options.LOW_RES_MV;
    key.FFX_MLSR_AUTOEXPOSURE_ENABLED = options.AUTOEXPOSURE_ENABLED;
    key.FFX_MLSR_COLORSPACE = colorspace(options);
    key.FFX_MLSR_JITTERED_MOTION_VECTORS = options.JITTERED_MOTION_VECTORS;
    key.FFX_MLSR_RESOLUTION = static_cast<uint32_t>(options.maxRes);
    key.FFX_DEBUG_VISUALIZE = options.DEBUG_VISUALIZE;
    return FSR4N10_ASSIGN_BLOB(key.index, fsr4_model_v07_i8_native_0);
}

FfxShaderBlob fsr4_shaders::GetPostShaderBlob(uint32_t permutationOption) {
    const auto options = PermutationOptionsFromKey(permutationOption);
    if (!supports_navi10_native_1080(options)) {
        return {};
    }

    fsr4_model_v07_i8_native_13_PermutationKey key{};
    key.FFX_MLSR_COLORSPACE = colorspace(options);
    key.AUTOEXPOSURE_ENABLED = options.AUTOEXPOSURE_ENABLED;
    key.FFX_DEBUG_VISUALIZE = options.DEBUG_VISUALIZE;
    key.RESOLUTION = static_cast<uint32_t>(options.maxRes);
    return FSR4N10_ASSIGN_BLOB(key.index, fsr4_model_v07_i8_native_13);
}

FfxShaderBlob fsr4_shaders::GetModelShaderBlob(unsigned int pass, uint32_t permutationOption) {
    const auto options = PermutationOptionsFromKey(permutationOption);
    if (!supports_navi10_native_1080(options)) {
        return {};
    }

    switch (pass) {
    case 1: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_1);
    case 2: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_2);
    case 3: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_3);
    case 4: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_4);
    case 5: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_5);
    case 6: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_6);
    case 7: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_7);
    case 8: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_8);
    case 9: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_9);
    case 10: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_10);
    case 11: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_11);
    case 12: return FSR4N10_ASSIGN_BLOB(0, fsr4_model_v07_i8_native_1080_12);
    default: return {};
    }
}

FfxShaderBlob fsr4_shaders::GetPaddingResetBlob(unsigned int, uint32_t) {
    return {};
}

FfxShaderBlob fsr4_shaders::GetSPDAutoExposureBlob() {
    return FSR4N10_ASSIGN_BLOB(0, spd_auto_exposure);
}

FfxShaderBlob fsr4_shaders::GetDebugViewBlob(uint32_t permutationOption) {
    const auto options = PermutationOptionsFromKey(permutationOption);
    if (!supports_navi10_native_1080(options)) {
        return {};
    }
    debug_view_PermutationKey key{};
    key.FFX_MLSR_JITTERED_MOTION_VECTORS = options.JITTERED_MOTION_VECTORS;
    return FSR4N10_ASSIGN_BLOB(key.index, debug_view);
}

FfxShaderBlob fsr4_shaders::GetRcasBlob(uint32_t permutationOption) {
    const auto options = PermutationOptionsFromKey(permutationOption);
    if (!supports_navi10_native_1080(options)) {
        return {};
    }
    rcas_PermutationKey key{};
    key.FFX_MLSR_AUTOEXPOSURE_ENABLED = options.AUTOEXPOSURE_ENABLED;
    key.FFX_MLSR_COLORSPACE = colorspace(options);
    return FSR4N10_ASSIGN_BLOB(key.index, rcas);
}

void fsr4_shaders::GetInitializer(Preset preset, bool is_wmma, void*& outBlobPointer, size_t& outBlobSize) {
    outBlobPointer = nullptr;
    outBlobSize = 0;
    if (preset == Preset::NativeAA && !is_wmma) {
        outBlobPointer = const_cast<unsigned char*>(g_fsr4_model_v07_i8_native_initializers_data);
        outBlobSize = g_fsr4_model_v07_i8_native_initializers_size;
    }
}

size_t fsr4_shaders::GetInitializerSize() {
    return g_fsr4_model_v07_i8_native_initializers_size;
}

size_t fsr4_shaders::GetScratchSize(MaxResolution resolution) {
    switch (resolution) {
    case MaxResolution::Res_1920_1080: return 20880256;
    case MaxResolution::Res_3840_2160: return 83232256;
    case MaxResolution::Res_7680_4320: return 332352256;
    default: return 332352256;
    }
}

#undef FSR4N10_ASSIGN_BLOB
