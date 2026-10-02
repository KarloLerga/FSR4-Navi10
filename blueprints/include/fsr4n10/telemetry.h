#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace fsr4n10 {

struct PassTiming {
    std::string passName;
    std::string variantId;
    double gpuMilliseconds = 0.0;
};

struct RunTelemetry {
    std::string adapterName;
    std::string driverVersion;
    std::string backend;
    std::string modelHash;
    std::string shaderPackHash;
    std::uint32_t renderWidth = 0;
    std::uint32_t renderHeight = 0;
    std::uint32_t outputWidth = 0;
    std::uint32_t outputHeight = 0;
    double totalGpuMilliseconds = 0.0;
    std::vector<PassTiming> passes;
};

} // namespace fsr4n10
