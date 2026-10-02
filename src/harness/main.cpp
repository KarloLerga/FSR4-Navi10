#include "fsr4n10/device_caps.h"
#include "fsr4n10/fp16_probe.h"
#include "fsr4n10/model_pack.h"
#include "fsr4n10/naviqsr_gpu.h"
#include "fsr4n10/upstream_smoke.h"
#include "fsr4n10/version.h"

#include <filesystem>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string_view>

namespace {

void print_usage() {
    std::cout << "FSR4-Navi10 " << FSR4N10_VERSION_STRING << "\n"
              << "Usage:\n"
              << "  fsr4n10_harness.exe --version\n"
              << "  fsr4n10_harness.exe --list-adapters\n"
              << "  fsr4n10_harness.exe --run-fp16-probe\n"
              << "  fsr4n10_harness.exe --run-upstream-pass0-smoke\n"
              << "  fsr4n10_harness.exe --run-upstream-i8-zero-model-smoke\n"
              << "  fsr4n10_harness.exe --benchmark-upstream-i8-zero-model\n"
              << "  fsr4n10_harness.exe --run-upstream-i8-image-smoke <input.ppm> <output.bmp>\n"
              << "  fsr4n10_harness.exe --validate-model-pack <path>\n"
              << "  fsr4n10_harness.exe --run-naviqsr-analytic-gpu <case.nqsrtest>\n"
              << "  fsr4n10_harness.exe --run-naviqsr-network-gpu <case.nqsrframe>\n";
}

int list_adapters() {
    const auto adapters = fsr4n10::enumerate_adapters();
    if (adapters.empty()) {
        std::cout << "No hardware DXGI adapters found.\n";
        return 0;
    }

    for (const auto& adapter : adapters) {
        std::cout << "Adapter " << adapter.adapterIndex << ": " << adapter.name << '\n'
                  << "  PCI: " << std::hex << std::setfill('0') << std::setw(4) << adapter.vendorId
                  << ':' << std::setw(4) << adapter.deviceId << std::dec << '\n'
                  << "  Dedicated VRAM: " << (adapter.dedicatedVideoMemoryBytes / (1024U * 1024U)) << " MiB\n"
                  << "  D3D12: " << (adapter.supportsD3D12 ? "yes" : "no")
                  << ", shader model: " << fsr4n10::shader_model_name(adapter.shaderModel) << '\n'
                  << "  Wave ops: " << (adapter.supportsWaveOps ? "yes" : "no")
                  << ", lane range: " << adapter.waveLaneMin << "-" << adapter.waveLaneMax << '\n'
                  << "  Native 16-bit shader ops: " << (adapter.supportsNative16BitShaderOps ? "yes" : "no")
                  << ", resource binding tier: " << adapter.resourceBindingTier << '\n'
                  << "  RX 5700 XT target: " << (adapter.isRx5700Xt ? "yes (gfx1010 target)" : "no") << '\n';
    }
    return 0;
}

int validate_model_pack(const std::filesystem::path& path) {
    const auto pack = fsr4n10::ModelPack::Load(path);
    std::uint64_t total_parameter_bytes = 0;
    for (std::size_t index = 0; index < pack.tensors().size(); ++index) {
        total_parameter_bytes += pack.tensor_bytes(index).size();
    }
    std::cout << "Model pack valid: " << pack.tensors().size() << " FP16 tensors, " << total_parameter_bytes
              << " parameter bytes. First tensor: " << pack.tensor_name(0) << ".\n";
    return 0;
}

} // namespace

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string_view(argv[1]) == "--version") {
            std::cout << "FSR4-Navi10 " << FSR4N10_VERSION_STRING << '\n';
            return 0;
        }
        if (argc == 2 && std::string_view(argv[1]) == "--list-adapters") {
            return list_adapters();
        }
        if (argc == 2 && std::string_view(argv[1]) == "--run-fp16-probe") {
            return fsr4n10::run_fp16_probe();
        }
        if (argc == 2 && std::string_view(argv[1]) == "--run-upstream-pass0-smoke") {
            return fsr4n10::run_upstream_pass0_smoke();
        }
        if (argc == 2 && std::string_view(argv[1]) == "--run-upstream-i8-zero-model-smoke") {
            return fsr4n10::run_upstream_i8_zero_model_smoke();
        }
        if (argc == 2 && std::string_view(argv[1]) == "--benchmark-upstream-i8-zero-model") {
            return fsr4n10::run_upstream_i8_zero_model_benchmark();
        }
        if (argc == 4 && std::string_view(argv[1]) == "--run-upstream-i8-image-smoke") {
            return fsr4n10::run_upstream_i8_image_smoke(argv[2], argv[3]);
        }
        if (argc == 3 && std::string_view(argv[1]) == "--validate-model-pack") {
            return validate_model_pack(std::filesystem::path(argv[2]));
        }
        if (argc == 3 && std::string_view(argv[1]) == "--run-naviqsr-analytic-gpu") {
            return fsr4n10::run_naviqsr_analytic_gpu_smoke(std::filesystem::path(argv[2]));
        }
        if (argc == 3 && std::string_view(argv[1]) == "--run-naviqsr-network-gpu") {
            return fsr4n10::run_naviqsr_network_gpu_smoke(std::filesystem::path(argv[2]));
        }
        print_usage();
        return argc == 1 ? 0 : 2;
    } catch (const std::exception& error) {
        std::cerr << "fsr4n10_harness: " << error.what() << '\n';
        return 1;
    }
}
