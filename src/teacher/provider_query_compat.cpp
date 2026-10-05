// This file is part of the FSR4-Navi10 project.
//
// Copyright (C) 2026 Karlo Lerga
//
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.

// The pinned FSR4 provider's vtable includes generic query entry points that
// reference these four small FSR3 helpers. This compatibility translation unit
// keeps the Navi10 teacher target independent of the generated FSR3 shader set.
// The formulas match the corresponding helper functions in the pinned
// FidelityFX source: Kits/FidelityFX/upscalers/fsr3/internal/ffx_fsr3upscaler.cpp.

#include "ffx_fsr3upscaler.h"

#include <cmath>
#include <cstdint>

namespace {

float halton(int32_t index, int32_t base) {
    float factor = 1.0f;
    float result = 0.0f;
    for (int32_t current = index; current > 0;) {
        factor /= static_cast<float>(base);
        result += factor * static_cast<float>(current % base);
        current = static_cast<uint32_t>(std::floor(static_cast<float>(current) / static_cast<float>(base)));
    }
    return result;
}

} // namespace

float ffxFsr3UpscalerGetUpscaleRatioFromQualityMode(FfxApiUpscaleQualityMode qualityMode) {
    switch (qualityMode) {
    case FFX_UPSCALE_QUALITY_MODE_NATIVEAA: return 1.0f;
    case FFX_UPSCALE_QUALITY_MODE_QUALITY: return 1.5f;
    case FFX_UPSCALE_QUALITY_MODE_BALANCED: return 1.7f;
    case FFX_UPSCALE_QUALITY_MODE_PERFORMANCE: return 2.0f;
    case FFX_UPSCALE_QUALITY_MODE_ULTRA_PERFORMANCE: return 3.0f;
    default: return 0.0f;
    }
}

FfxErrorCode ffxFsr3UpscalerGetRenderResolutionFromQualityMode(
    uint32_t* renderWidth,
    uint32_t* renderHeight,
    uint32_t displayWidth,
    uint32_t displayHeight,
    FfxApiUpscaleQualityMode qualityMode) {
    if (renderWidth == nullptr || renderHeight == nullptr) {
        return FFX_ERROR_INVALID_POINTER;
    }
    if (qualityMode < FFX_UPSCALE_QUALITY_MODE_NATIVEAA ||
        qualityMode > FFX_UPSCALE_QUALITY_MODE_ULTRA_PERFORMANCE) {
        return FFX_ERROR_INVALID_ENUM;
    }
    const float ratio = ffxFsr3UpscalerGetUpscaleRatioFromQualityMode(qualityMode);
    *renderWidth = static_cast<uint32_t>(static_cast<float>(displayWidth) / ratio);
    *renderHeight = static_cast<uint32_t>(static_cast<float>(displayHeight) / ratio);
    return FFX_OK;
}

int32_t ffxFsr3UpscalerGetJitterPhaseCount(int32_t renderWidth, int32_t displayWidth) {
    const float ratio = static_cast<float>(displayWidth) / static_cast<float>(renderWidth);
    return static_cast<int32_t>(8.0f * std::pow(ratio, 2.0f));
}

FfxErrorCode ffxFsr3UpscalerGetJitterOffset(float* outX, float* outY, int32_t index, int32_t phaseCount) {
    if (outX == nullptr || outY == nullptr) {
        return FFX_ERROR_INVALID_POINTER;
    }
    if (phaseCount <= 0) {
        return FFX_ERROR_INVALID_ARGUMENT;
    }
    const int32_t sequenceIndex = (index % phaseCount) + 1;
    *outX = halton(sequenceIndex, 2) - 0.5f;
    *outY = halton(sequenceIndex, 3) - 0.5f;
    return FFX_OK;
}
