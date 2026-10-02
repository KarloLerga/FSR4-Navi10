#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace fsr4n10 {

struct DeviceCaps {
    std::string name;
    std::uint32_t adapterIndex{};
    std::uint32_t vendorId{};
    std::uint32_t deviceId{};
    std::uint32_t subsystemId{};
    std::uint32_t revision{};
    std::uint64_t dedicatedVideoMemoryBytes{};
    std::int32_t luidHighPart{};
    std::uint32_t luidLowPart{};
    std::uint32_t shaderModel{};
    std::uint32_t resourceBindingTier{};
    std::uint32_t waveLaneMin{};
    std::uint32_t waveLaneMax{};
    bool supportsD3D12{};
    bool supportsWaveOps{};
    bool supportsNative16BitShaderOps{};
    bool isRx5700Xt{};
};

std::vector<DeviceCaps> enumerate_adapters();
std::string shader_model_name(std::uint32_t shader_model);

} // namespace fsr4n10
